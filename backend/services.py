"""
Service layer: assemble page-ready responses from the data layer, analytics, the
pricing engine, and the strategy math. The API routes stay thin and call these.

All network fetches funnel through here so caching and error handling live in one
place. Heavy chain pulls are cached briefly (the market data is last-session while
closed, so a short TTL is safe and keeps tab-switching fast).
"""
import datetime as dt
import math
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pricing_engine import (  # noqa: E402
    binomial_price, bs_price, breakeven_long_option, implied_vol, prob_itm,
    prob_profit_long_option,
)
from heston import heston_price  # noqa: E402

from backend.data import alpaca, dividends, normalize, rates, yfinance_client
from backend.data.alpaca import AlpacaError
from backend.data.yfinance_client import YFinanceError
from backend import analytics, commentary, hedging, heston_calib, montecarlo, strategy
from backend import surface as surface_mod
from backend.storage import db

_CHAIN_TTL = 180  # seconds
_BARS_TTL = 900
_CACHE = {}


class DataUnavailable(RuntimeError):
    """Raised when no source can satisfy a request."""


class NotFound(RuntimeError):
    """Raised when a specific contract cannot be located."""


def _cached(key, ttl, producer):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = producer()
    _CACHE[key] = (now, value)
    return value


# ----------------------------------------------------------------------
# Greek / contract serialization (display units per CLAUDE.md)
# ----------------------------------------------------------------------
GREEKS_UNITS = {
    "delta": "per $1 spot", "gamma": "per $1 spot",
    "vega": "per 1% vol", "theta": "per calendar day", "rho": "per 1% rate",
}


def greeks_display(g):
    """Convert engine-native Greeks to display units (vega/100, theta/365, rho/100)."""
    def scaled(v, factor):
        return None if v is None else v / factor
    return {
        "delta": g.delta, "gamma": g.gamma,
        "vega": scaled(g.vega, 100.0),
        "theta": scaled(g.theta, 365.0),
        "rho": scaled(g.rho, 100.0),
    }


def serialize_contract(c):
    return {
        "symbol": c.symbol, "type": c.option_type, "strike": c.strike,
        "expiration": c.expiration.isoformat(),
        "bid": c.bid, "ask": c.ask, "mid": c.mid, "last": c.last,
        "volume": c.volume, "open_interest": c.open_interest,
        "iv": c.iv, "iv_source": c.iv_source,
        "greeks": greeks_display(c.greeks), "greeks_source": c.greeks_source,
        "time_to_expiry": c.time_to_expiry, "rate_used": c.rate_used,
        "quote_timestamp": c.quote_timestamp, "in_the_money": c.in_the_money,
    }


# ----------------------------------------------------------------------
# Shared loaders
# ----------------------------------------------------------------------
def nearest_expiration_dates(ticker, n):
    exp_strs = yfinance_client.get_expirations(ticker)
    if not exp_strs:
        raise DataUnavailable(f"no expirations available for {ticker}")
    exp_strs = exp_strs[:n]
    return [dt.date.fromisoformat(e) for e in exp_strs], exp_strs


def _load_chain(ticker, exp_strs, exp_dates, iv_source, dividend_override,
                strike_band=0.3):
    key = ("chain", ticker, tuple(exp_strs), iv_source, dividend_override,
           strike_band)

    def produce():
        now = dt.datetime.now(dt.timezone.utc)
        today = now.date()
        spot = yfinance_client.get_spot(ticker)

        snaps = {}
        if iv_source in ("auto", "alpaca") and exp_dates:
            lo = spot * (1 - strike_band) if spot else None
            hi = spot * (1 + strike_band) if spot else None
            try:
                snaps = alpaca.get_option_snapshots(
                    ticker, expiration_gte=today, expiration_lte=exp_dates[-1],
                    strike_gte=lo, strike_lte=hi, feed="indicative", limit=1000,
                )
            except AlpacaError:
                snaps = {}

        yf_by_exp = {}
        if iv_source in ("auto", "yfinance"):
            for exp_str, exp_date in zip(exp_strs, exp_dates):
                try:
                    calls, puts = yfinance_client.get_option_chain(ticker, exp_str)
                    yf_by_exp[exp_date] = (calls, puts)
                except YFinanceError:
                    continue

        rate_fn, rate_source, rate_points, rate_asof = rates.get_rate_curve()
        q, q_source = dividends.resolve_dividend_yield(ticker, dividend_override)

        chain = normalize.build_chain(
            ticker, alpaca_snapshots=snaps, yfinance_by_expiration=yf_by_exp,
            spot=spot, rate_fn=rate_fn, dividend_yield=q, dividend_source=q_source,
            now=now, iv_source=iv_source,
        )
        meta = {
            "as_of": now.isoformat(), "spot": spot,
            "rate": {"source": rate_source, "as_of": rate_asof,
                     "points": {str(k): v for k, v in (rate_points or {}).items()}},
            "dividend": {"value": q, "source": q_source},
            "iv_source": iv_source,
        }
        return chain, meta, rate_fn, now

    return _cached(key, _CHAIN_TTL, produce)


def _load_bars(ticker, days=560):
    """Daily OHLC bars, enough history for a 60-day vol cone over a year."""
    key = ("bars", ticker, days)

    def produce():
        today = dt.date.today()
        return alpaca.get_stock_bars(ticker, start=today - dt.timedelta(days=days))

    return _cached(key, _BARS_TTL, produce)


def _load_closes(ticker):
    return [b["c"] for b in _load_bars(ticker)]


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
def market_status():
    try:
        clock = alpaca.get_clock()
        return {
            "is_open": clock.get("is_open"),
            "timestamp": clock.get("timestamp"),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
            "source": "alpaca",
        }
    except AlpacaError:
        return {"is_open": None, "source": "unavailable"}


def assumptions(ticker, dividend_override=None):
    rate_fn, rate_source, rate_points, rate_asof = rates.get_rate_curve()
    q, q_source = dividends.resolve_dividend_yield(ticker, dividend_override)
    sample = {t: rate_fn(t) for t in (0.25, 1.0, 2.0, 5.0)}
    return {
        "ticker": ticker,
        "rate": {"source": rate_source, "as_of": rate_asof,
                 "points": {str(k): v for k, v in (rate_points or {}).items()},
                 "sample": {str(k): v for k, v in sample.items()}},
        "dividend": {"value": q, "source": q_source},
    }


def expirations(ticker):
    exp_dates, exp_strs = nearest_expiration_dates(ticker, 60)
    return {"ticker": ticker, "expirations": exp_strs}


def chain_page(ticker, num_expirations=6, iv_source="auto", dividend_override=None):
    exp_dates, exp_strs = nearest_expiration_dates(ticker, num_expirations)
    chain, meta, _, _ = _load_chain(ticker, exp_strs, exp_dates, iv_source,
                                    dividend_override)
    iv_rank = None
    try:
        iv_rank = analytics.realized_vol_rank(_load_closes(ticker))
    except AlpacaError:
        iv_rank = None
    return {
        "ticker": ticker, "spot": chain.spot, "as_of": meta["as_of"],
        "rate": meta["rate"], "dividend": meta["dividend"],
        "iv_source": iv_source, "market": market_status(),
        "expirations": [d.isoformat() for d in chain.expirations],
        "iv_rank": iv_rank, "greeks_units": GREEKS_UNITS,
        "contracts": [serialize_contract(c) for c in chain.contracts],
    }


def contract_detail(ticker, symbol, iv_source="auto", dividend_override=None):
    underlying, exp, otype, strike = alpaca.parse_occ_symbol(symbol)
    chain, meta, _, _ = _load_chain(ticker, [exp.isoformat()], [exp], iv_source,
                                    dividend_override, strike_band=0.5)
    match = next((c for c in chain.contracts if c.symbol == symbol), None)
    if match is None:
        match = next(
            (c for c in chain.contracts
             if c.option_type == otype and abs(c.strike - strike) < 1e-6
             and c.expiration == exp),
            None,
        )
    if match is None:
        raise NotFound(f"contract {symbol} not found in chain")

    S, K = chain.spot, match.strike
    T, r, sigma = match.time_to_expiry, match.rate_used, match.iv
    q = meta["dividend"]["value"]

    bs = binom = early_ex = p_itm = pop = breakeven = None
    if sigma and S and T and T > 0:
        bs = bs_price(S, K, T, r, sigma, otype, q)
        binom = binomial_price(S, K, T, r, sigma, otype, q, steps=200, american=True)
        early_ex = binom - bs
        p_itm = prob_itm(S, K, T, r, sigma, otype, q)
        premium = match.mid if match.mid is not None else (match.last or bs)
        if premium:
            pop = prob_profit_long_option(S, K, T, r, sigma, otype, premium, q)
            breakeven = breakeven_long_option(K, premium, otype)

    out = {
        "symbol": symbol, "type": otype, "strike": K,
        "expiration": exp.isoformat(), "spot": S,
        "time_to_expiry": T, "rate_used": r, "iv": sigma, "dividend_yield": q,
        "pricing": {
            "black_scholes": bs, "binomial_american": binom,
            "early_exercise_premium": early_ex,
        },
        "greeks": greeks_display(match.greeks), "greeks_units": GREEKS_UNITS,
        "probability": {
            "prob_itm": p_itm, "prob_of_profit": pop, "breakeven": breakeven,
        },
        "market_data": {
            "bid": match.bid, "ask": match.ask, "mid": match.mid,
            "last": match.last, "volume": match.volume,
            "open_interest": match.open_interest, "iv_source": match.iv_source,
            "quote_timestamp": match.quote_timestamp,
        },
        "as_of": meta["as_of"], "iv_source": iv_source,
    }
    out["read"] = commentary.contract_read(out, ticker)
    return out


def realized_vs_implied(ticker):
    bars = _load_bars(ticker)
    closes = [b["c"] for b in bars]
    if len(closes) < 20:
        raise DataUnavailable(f"insufficient price history for {ticker}")

    cc = analytics.realized_vol_windows(closes)      # close-to-close
    gk = analytics.garman_klass_windows(bars)        # Garman-Klass (primary)
    rank = analytics.realized_vol_rank(closes)
    cone = analytics.vol_cone(bars)
    divergence = analytics.gk_cc_divergence(gk, cc, window=20)

    # Match the implied tenor to the 20-day realized window so the premium
    # compares like horizons. 20 trading days is roughly 28 calendar days, so take
    # the expiration nearest one month out rather than the nearest overall, which
    # can be 0DTE and prints a degenerate ATM IV.
    target_days = 28
    all_dates, all_strs = nearest_expiration_dates(ticker, 12)
    today = dt.date.today()
    idx = min(range(len(all_dates)),
              key=lambda i: abs((all_dates[i] - today).days - target_days))
    exp_date, exp_str = all_dates[idx], all_strs[idx]
    chain, _, _, _ = _load_chain(ticker, [exp_str], [exp_date], "auto", None,
                                 strike_band=0.3)
    atm = analytics.atm_iv(chain)

    # Volatility risk premium: ATM implied vs 20-day realized (Garman-Klass, the
    # primary measure). Spread in vol points and the implied/realized ratio.
    gk20 = gk.get(20)
    vrp = None
    if atm and gk20:
        vrp = {"spread": atm - gk20, "ratio": atm / gk20, "basis": "gk_20"}

    read = commentary.realized_implied_read(atm, gk20, cone.get("20"), divergence)

    return {
        "ticker": ticker, "spot": chain.spot,
        "atm_iv": atm, "atm_expiration": exp_date.isoformat(),
        "realized_vol": {str(w): v for w, v in gk.items()},        # primary = GK
        "realized_vol_gk": {str(w): v for w, v in gk.items()},
        "realized_vol_cc": {str(w): v for w, v in cc.items()},
        "iv_rank": rank,
        "vrp": vrp,
        "divergence": divergence,
        "cone": cone,
        "read": read,
    }


def _atm_iv_1m(ticker):
    """ATM implied vol of the expiration nearest one month out, or None."""
    all_dates, all_strs = nearest_expiration_dates(ticker, 12)
    today = dt.date.today()
    idx = min(range(len(all_dates)),
              key=lambda i: abs((all_dates[i] - today).days - 28))
    chain, _, _, _ = _load_chain(ticker, [all_strs[idx]], [all_dates[idx]], "auto",
                                 None, strike_band=0.3)
    return analytics.atm_iv(chain)


def hedge_simulation(ticker, lookback=30, implied_vol=None, option_type="call",
                     position=1, moneyness=1.0):
    """Delta-hedge one option over the last `lookback` trading days of the path."""
    bars = _load_bars(ticker)
    if len(bars) < lookback + 2:
        raise DataUnavailable(f"insufficient price history for {ticker}")
    window = bars[-(lookback + 1):]
    closes = [b["c"] for b in window]
    dates = [str(b.get("t", ""))[:10] for b in window]

    if implied_vol is None:
        implied_vol = _atm_iv_1m(ticker) or hedging.realized_vol(closes)
    if not implied_vol or implied_vol <= 0:
        raise DataUnavailable("no implied vol available to hedge at")

    T = lookback / 252
    rate_fn, rate_source, _, rate_asof = rates.get_rate_curve()
    r = rate_fn(T)
    q, _ = dividends.resolve_dividend_yield(ticker, None)

    result = hedging.simulate(closes, implied_vol, r, q, option_type, position, moneyness)
    if result is None:
        raise DataUnavailable("could not simulate the hedge over this window")
    for step, date in zip(result["steps"], dates):
        step["date"] = date
    result["ticker"] = ticker
    result["as_of"] = dates[-1]
    result["rate_used"] = r
    result["dividend_yield"] = q
    result["read"] = commentary.hedge_read(result["summary"])
    return result


def surface(ticker, max_expirations=8, iv_source="auto"):
    exp_dates, exp_strs = nearest_expiration_dates(ticker, max_expirations)
    chain, meta, rate_fn, now = _load_chain(ticker, exp_strs, exp_dates, iv_source,
                                            None, strike_band=0.5)
    spot = chain.spot
    q = meta["dividend"]["value"]
    forwards = {}
    for exp in chain.expirations:
        T = normalize.time_to_expiry(exp, now)
        forwards[exp] = (spot * math.exp((rate_fn(T) - q) * T)
                         if (spot and T > 0) else spot)

    svi = surface_mod.svi_surface(chain, forwards)
    arb = surface_mod.arbitrage(chain, forwards, spot, rate_fn, q)
    term = surface_mod.atm_term_structure(chain, forwards, svi)
    term["read"] = commentary.term_structure_read(term.get("points"))
    return {
        "ticker": ticker, "spot": spot, "as_of": meta["as_of"],
        "expirations": [d.isoformat() for d in chain.expirations],
        "points": analytics.surface_points(chain),
        "svi": svi, "arbitrage": arb, "term_structure": term,
    }


_HESTON_TTL = 300  # calibration is expensive and the chain is slow-moving


def _heston_surface_grid(params, spot, rate_fn, q, tenor_lo, tenor_hi):
    """Heston-implied vol mesh over a near-money band and the calibrated tenor span."""
    v0, kappa, theta, xi, rho = (params[k] for k in ("v0", "kappa", "theta", "xi", "rho"))
    strikes = [spot * 0.8 + spot * 0.4 * i / 39 for i in range(40)]
    tenors = [tenor_lo + (tenor_hi - tenor_lo) * j / 15 for j in range(16)]
    z = []
    for T in tenors:
        r = rate_fn(T)
        row = []
        for K in strikes:
            price = heston_price(spot, K, T, r, v0, kappa, theta, xi, rho, "call", q)
            iv = implied_vol(price, spot, K, T, r, "call", q)
            row.append(round(iv * 100, 3) if iv else None)
        z.append(row)
    return {"strikes": [round(s, 2) for s in strikes],
            "tenors": [round(t, 4) for t in tenors], "z": z}


def heston_calibration(ticker):
    """Calibrate Heston to a maturity-diverse slice of the chain. Cached per ticker."""
    def produce():
        all_dates, _ = nearest_expiration_dates(ticker, 60)
        chosen = heston_calib.select_expirations(all_dates, dt.date.today())
        if len(chosen) < 3:
            return {"ok": False, "reason": "not enough distinct maturities",
                    "spot": None, "as_of": None, "surface": None, "points": []}
        chosen_strs = [d.isoformat() for d in chosen]
        chain, meta, rate_fn, now = _load_chain(ticker, chosen_strs, chosen, "auto",
                                                None, strike_band=0.5)
        spot = chain.spot
        q = meta["dividend"]["value"]
        result = heston_calib.calibrate_from_chain(chain, spot, rate_fn, q)
        result["spot"] = spot
        result["as_of"] = meta["as_of"]
        result["points"] = analytics.surface_points(chain)
        if result.get("ok") and result.get("per_expiration"):
            tenors = [pe["tenor"] for pe in result["per_expiration"]]
            result["surface"] = _heston_surface_grid(result["params"], spot, rate_fn,
                                                      q, min(tenors), max(tenors))
        else:
            result["surface"] = None
        return result

    return _cached(("heston", ticker), _HESTON_TTL, produce)


def contract_heston(ticker, symbol):
    """Heston price for one contract from the cached whole-chain calibration."""
    _, exp, otype, strike = alpaca.parse_occ_symbol(symbol)
    chain, meta, _, _ = _load_chain(ticker, [exp.isoformat()], [exp], "auto", None,
                                    strike_band=0.5)
    match = next((c for c in chain.contracts if c.symbol == symbol), None)
    if match is None:
        match = next((c for c in chain.contracts
                      if c.option_type == otype and abs(c.strike - strike) < 1e-6
                      and c.expiration == exp), None)
    if match is None:
        raise NotFound(f"contract {symbol} not found in chain")

    S, K, T, r, sigma = chain.spot, match.strike, match.time_to_expiry, match.rate_used, match.iv
    q = meta["dividend"]["value"]
    calib = heston_calibration(ticker)
    if not calib.get("ok"):
        return {"ok": False, "reason": calib.get("reason") or "calibration unavailable",
                "price": None, "iv": None, "iv_rmse": calib.get("iv_rmse"),
                "params": None, "read": None}

    p = calib["params"]
    price = heston_iv = None
    if S and T and T > 0:
        price = heston_price(S, K, T, r, p["v0"], p["kappa"], p["theta"], p["xi"],
                             p["rho"], otype, q)
        heston_iv = implied_vol(price, S, K, T, r, otype, q)
    return {
        "ok": True, "price": price, "iv": heston_iv, "market_iv": sigma,
        "iv_rmse": calib.get("iv_rmse"), "feller_ok": calib.get("feller_ok"),
        "params": p,
        "read": commentary.heston_contract_read(price, heston_iv, sigma, calib.get("iv_rmse")),
    }


def contract_montecarlo(ticker, symbol):
    """Monte Carlo vanilla price plus a convergence series for one contract."""
    _, exp, otype, strike = alpaca.parse_occ_symbol(symbol)
    chain, meta, _, _ = _load_chain(ticker, [exp.isoformat()], [exp], "auto", None,
                                    strike_band=0.5)
    match = next((c for c in chain.contracts if c.symbol == symbol), None)
    if match is None:
        match = next((c for c in chain.contracts
                      if c.option_type == otype and abs(c.strike - strike) < 1e-6
                      and c.expiration == exp), None)
    if match is None:
        raise NotFound(f"contract {symbol} not found in chain")

    S, K, T, r, sigma = chain.spot, match.strike, match.time_to_expiry, match.rate_used, match.iv
    q = meta["dividend"]["value"]
    if not (S and T and T > 0 and sigma):
        return {"ok": False, "reason": "contract not priceable", "price": None,
                "convergence": [], "read": None}
    mc = montecarlo.price_european(S, K, T, r, sigma, otype, q)
    bs = bs_price(S, K, T, r, sigma, otype, q)
    return {
        "ok": True, "price": mc["price"], "ci_low": mc["ci_low"], "ci_high": mc["ci_high"],
        "stderr": mc["stderr"], "n_paths": mc["n_paths"], "bs": bs,
        "convergence": montecarlo.european_convergence(S, K, T, r, sigma, otype, q),
        "read": commentary.montecarlo_read(mc["price"], mc["ci_low"], mc["ci_high"], bs),
    }


def montecarlo_exotic(ticker, kind="asian", option_type="call", days=60, moneyness=1.0,
                      implied_vol=None, average="arithmetic", barrier_moneyness=1.1,
                      barrier_type="up-and-out"):
    """Price a path-dependent option on the underlying, with the vanilla for contrast."""
    spot = yfinance_client.get_spot(ticker)
    if not spot:
        raise DataUnavailable(f"no spot price for {ticker}")
    sigma = implied_vol if implied_vol else _atm_iv_1m(ticker)
    if not sigma or sigma <= 0:
        raise DataUnavailable("no implied vol available for the exotic")
    T = days / 365.0
    rate_fn, *_ = rates.get_rate_curve()
    r = rate_fn(T)
    q, _ = dividends.resolve_dividend_yield(ticker, None)
    K = spot * moneyness

    knock = None
    if kind == "barrier":
        barrier = spot * barrier_moneyness
        exotic = montecarlo.price_barrier(spot, K, T, r, sigma, barrier, barrier_type,
                                          option_type, q)
        knock = exotic.get("knock_probability") if exotic else None
    else:
        kind = "asian"
        exotic = montecarlo.price_asian(spot, K, T, r, sigma, option_type, q, average=average)
    if exotic is None:
        raise DataUnavailable("could not price the exotic over these inputs")

    vanilla_mc = montecarlo.price_european(spot, K, T, r, sigma, option_type, q)
    vanilla_bs = bs_price(spot, K, T, r, sigma, option_type, q)
    barrier_level = spot * barrier_moneyness if kind == "barrier" else None
    sample = montecarlo.sample_paths(spot, T, r, sigma, q, n_paths=200, n_steps=80,
                                     barrier=barrier_level,
                                     barrier_type=barrier_type if kind == "barrier" else None)
    return {
        "ok": True, "ticker": ticker, "kind": kind, "option_type": option_type,
        "spot": spot, "strike": K, "implied_vol": sigma, "days": days,
        "price": exotic["price"], "ci_low": exotic["ci_low"], "ci_high": exotic["ci_high"],
        "stderr": exotic["stderr"], "knock_probability": knock,
        "average": average if kind == "asian" else None,
        "barrier": barrier_level,
        "barrier_type": barrier_type if kind == "barrier" else None,
        "vanilla_bs": vanilla_bs, "vanilla_mc": vanilla_mc["price"],
        "paths": sample,
        "read": commentary.exotic_read(kind, option_type, exotic["price"], vanilla_bs,
                                       knock, average, barrier_type),
    }


def _skew_metrics(chain, exp, forward):
    """
    ATM IV (at the forward), the 25-delta risk reversal (call IV minus put IV) and
    the 25-delta butterfly (wing average above ATM). Uses the per-strike reconciled
    IV and the recomputed deltas already on the chain, for the target expiration
    only (the loaded chain can include nearer expirations from the Alpaca pull).
    """
    contracts = [c for c in chain.contracts if c.expiration == exp]
    calls = [c for c in contracts
             if c.option_type == "call" and c.iv and c.greeks.delta is not None]
    puts = [c for c in contracts
            if c.option_type == "put" and c.iv and c.greeks.delta is not None]
    c25 = min(calls, key=lambda c: abs(c.greeks.delta - 0.25), default=None)
    p25 = min(puts, key=lambda c: abs(c.greeks.delta + 0.25), default=None)
    # Only trust a 25-delta strike if one actually lands near 0.25. Near expiry the
    # delta steps from ~0 to ~1 with no strike in between, so the metric is undefined.
    if c25 and abs(c25.greeks.delta - 0.25) > 0.12:
        c25 = None
    if p25 and abs(p25.greeks.delta + 0.25) > 0.12:
        p25 = None

    per_strike = {}
    for c in contracts:
        if c.iv and c.strike not in per_strike:
            per_strike[c.strike] = c.iv
    atm_iv = rates.interpolate_rate(forward, per_strike) if per_strike else None

    rr = (c25.iv - p25.iv) if (c25 and p25) else None
    bf = ((c25.iv + p25.iv) / 2 - atm_iv) if (c25 and p25 and atm_iv) else None

    def leg(c):
        return {"strike": c.strike, "iv": c.iv, "delta": c.greeks.delta} if c else None

    return {"atm_iv": atm_iv, "rr_25": rr, "bf_25": bf,
            "call_25": leg(c25), "put_25": leg(p25)}


def smile(ticker, expiration_str, iv_source="auto"):
    exp = dt.date.fromisoformat(expiration_str)
    chain, meta, rate_fn, now = _load_chain(ticker, [expiration_str], [exp],
                                            iv_source, None, strike_band=0.5)
    spot = chain.spot
    T = normalize.time_to_expiry(exp, now)
    r = rate_fn(T) if rate_fn else 0.0
    q = meta["dividend"]["value"]
    forward = spot * math.exp((r - q) * T) if (spot and T > 0) else spot
    metrics = _skew_metrics(chain, exp, forward) if spot else {}
    return {
        "ticker": ticker, "expiration": expiration_str,
        "spot": spot, "forward": forward, "r": r, "q": q, "t": T,
        "as_of": meta["as_of"],
        "atm_iv": metrics.get("atm_iv"),
        "rr_25": metrics.get("rr_25"), "bf_25": metrics.get("bf_25"),
        "call_25": metrics.get("call_25"), "put_25": metrics.get("put_25"),
        "points": analytics.smile_points(chain, exp),
    }


# ----------------------------------------------------------------------
# Strategy
# ----------------------------------------------------------------------
def _fill_leg_sigmas(legs, ticker, iv_source, dividend_override):
    """Populate any option leg missing sigma from the live chain at its expiration."""
    need = {leg.expiration for leg in legs
            if leg.is_option() and leg.sigma is None and leg.expiration}
    if not need:
        return
    lookup = {}
    for exp in need:
        try:
            chain, _, _, _ = _load_chain(
                ticker, [exp.isoformat()], [exp], iv_source, dividend_override,
                strike_band=0.6,
            )
        except (AlpacaError, YFinanceError, DataUnavailable):
            continue
        for c in chain.contracts:
            if c.iv:
                lookup[(c.option_type, round(c.strike, 3), c.expiration)] = c.iv
    for leg in legs:
        if leg.is_option() and leg.sigma is None:
            leg.sigma = lookup.get((leg.option_type, round(leg.strike, 3),
                                    leg.expiration))


def _valuation_dates(now, final_exp):
    """now, two dates on the way to expiry, and the expiration itself."""
    expiry_dt = dt.datetime(final_exp.year, final_exp.month, final_exp.day,
                            20, 0, 0, tzinfo=dt.timezone.utc)
    span = (expiry_dt - now).total_seconds()
    dates = [("now", now)]
    if span > 0:
        for frac in (0.5, 0.85):
            d = now + dt.timedelta(seconds=span * frac)
            dates.append((d.date().isoformat(), d))
    dates.append(("expiry", expiry_dt))
    return dates


def price_strategy(ticker, legs, iv_source="auto", dividend_override=None):
    now = dt.datetime.now(dt.timezone.utc)
    spot = yfinance_client.get_spot(ticker)
    if not spot:
        raise DataUnavailable(f"no spot price for {ticker}")
    rate_fn, rate_source, _, rate_asof = rates.get_rate_curve()
    q, q_source = dividends.resolve_dividend_yield(ticker, dividend_override)
    ctx = strategy.MarketContext(spot=spot, now=now, rate_fn=rate_fn,
                                 dividend_yield=q)

    _fill_leg_sigmas(legs, ticker, iv_source, dividend_override)
    missing = [i for i, leg in enumerate(legs)
               if leg.is_option() and not leg.sigma]
    if missing:
        raise DataUnavailable(
            f"no IV available for leg(s) {missing}; supply sigma or entry_price")

    summary = strategy.summarize(legs, ctx)
    final_exp = strategy._final_expiration(legs)
    curves_payload = {}
    xs = []
    if final_exp:
        labeled = _valuation_dates(now, final_exp)
        xs, curves = strategy.payoff_curve(legs, ctx, [d for _, d in labeled])
        for (label, d), series_key in zip(labeled, [d for _, d in labeled]):
            curves_payload[label] = curves[series_key]

    summary_out = {
        "net_cost": summary["net_cost"],
        "greeks": {
            "delta": summary["greeks"]["delta"],
            "gamma": summary["greeks"]["gamma"],
            "vega": summary["greeks"]["vega"] / 100.0,
            "theta": summary["greeks"]["theta"] / 365.0,
            "rho": summary["greeks"]["rho"] / 100.0,
        },
        "greeks_units": GREEKS_UNITS,
        "breakevens": summary["breakevens"],
        "max_profit": summary["max_profit"],
        "max_loss": summary["max_loss"],
        "prob_of_profit": summary["prob_of_profit"],
    }

    return {
        "ticker": ticker, "spot": spot, "as_of": now.isoformat(),
        "context": {"rate_source": rate_source, "rate_as_of": rate_asof,
                    "dividend": {"value": q, "source": q_source},
                    "iv_source": iv_source},
        "summary": summary_out,
        "read": commentary.strategy_read(summary_out, spot, ticker),
        "legs": strategy.leg_breakdown(legs, ctx),
        "payoff": {"underlying": xs, "curves": curves_payload},
    }


# ----------------------------------------------------------------------
# History (SQLite-backed)
# ----------------------------------------------------------------------
def record_visit(ticker, iv_source="auto"):
    """
    Compute the key metrics for a ticker and store one visit row. The frontend
    calls this when the user actively examines a ticker; recording is explicit so
    tab-switches and cache hits do not pad the history.
    """
    now = dt.datetime.now(dt.timezone.utc)
    closes = _load_closes(ticker)
    rv = analytics.realized_vol_windows(closes)
    rank = analytics.realized_vol_rank(closes)
    exp_dates, exp_strs = nearest_expiration_dates(ticker, 1)
    chain, _, _, _ = _load_chain(ticker, exp_strs, exp_dates, iv_source, None,
                                 strike_band=0.3)
    metrics = {
        "spot": chain.spot,
        "atm_iv": analytics.atm_iv(chain),
        "rv_10": rv.get(10), "rv_20": rv.get(20),
        "rv_30": rv.get(30), "rv_60": rv.get(60),
        "iv_rank": rank.get("rank") if rank else None,
        "iv_percentile": rank.get("percentile") if rank else None,
    }
    return db.record_visit(ticker, metrics, now.isoformat())


def history_visits(ticker=None, limit=200):
    return {"visits": db.list_visits(ticker, limit)}


def history_tickers():
    return {"tickers": db.distinct_tickers()}


def history_series(tickers, metric):
    return {"metric": metric, "series": db.metric_series(tickers, metric)}
