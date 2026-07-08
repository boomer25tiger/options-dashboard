"""
Normalize Alpaca and yfinance option data into one contract schema, back-solve
missing IV from the mid price, and recompute Greeks against the current clock so
time decay stays accurate over closed periods.

The IV-source policy:
  'alpaca'   -> use only Alpaca contracts; back-solve IV where Alpaca lacks it.
  'yfinance' -> use only yfinance contracts (its published IV).
  'auto'     -> Alpaca as the base; borrow yfinance IV / volume / OI where Alpaca
                is missing them, and add yfinance-only contracts. Back-solve last.
"""
import datetime as dt
import os
import sys

# The pricing engine lives at the project root as the single source of truth.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pricing_engine import bs_greeks, implied_vol  # noqa: E402

from backend.data.alpaca import parse_occ_symbol
from backend.data.models import Greeks, OptionChain, OptionContract

_DAYS_PER_YEAR = 365.0
# US equity options settle at market close; approximate expiry at 20:00 UTC (~16:00 ET).
_EXPIRY_HOUR_UTC = 20
# Above this, an IV is treated as unreliable and dropped. Deep-wing short-dated
# options back-solved from a one-tick penny quote yield 150-300% noise that sits
# far above any real SPY-style level (~10-25%). A generous 1.5 (150%) cap removes
# that noise without clipping realistic IV. Applies to all sources; tunable per
# ticker later if a genuinely high-vol name needs more headroom.
_IV_MAX_PLAUSIBLE = 1.5
# Below this an equity-option IV is degenerate. Over a multi-day market close the
# providers stop quoting (bid=ask=0) and report a near-zero IV, while the last
# trade price stays intact; treat such IVs as missing and back-solve from price.
_IV_MIN_TRUST = 0.02


def _time_to_expiry(expiration, now):
    expiry_dt = dt.datetime(
        expiration.year, expiration.month, expiration.day,
        _EXPIRY_HOUR_UTC, 0, 0, tzinfo=dt.timezone.utc,
    )
    seconds = (expiry_dt - now).total_seconds()
    return max(seconds, 0.0) / (_DAYS_PER_YEAR * 24 * 3600)


def time_to_expiry(expiration, now):
    """Public wrapper for the shared time-to-expiry convention (years, expiry ~16:00 ET)."""
    return _time_to_expiry(expiration, now)


def _mid(bid, ask):
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return 0.5 * (bid + ask)
    return None


def _key(option_type, strike, expiration):
    return (option_type, round(float(strike), 3), expiration)


def _num(value):
    """Coerce to float, treating NaN and None as missing."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


# ----------------------------------------------------------------------
# Source adapters -> partially filled OptionContract (no Greeks / T yet)
# ----------------------------------------------------------------------
def contract_from_alpaca(symbol, snap):
    underlying, expiration, option_type, strike = parse_occ_symbol(symbol)
    quote = snap.get("latestQuote") or {}
    trade = snap.get("latestTrade") or {}
    day = snap.get("dailyBar") or {}
    bid, ask = _num(quote.get("bp")), _num(quote.get("ap"))
    iv = _num(snap.get("impliedVolatility"))
    return OptionContract(
        symbol=symbol,
        underlying=underlying,
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        bid=bid,
        ask=ask,
        mid=_mid(bid, ask),
        last=_num(trade.get("p")),
        volume=_num(day.get("v")),
        open_interest=None,
        iv=iv,
        iv_source="alpaca" if iv is not None else None,
        quote_timestamp=quote.get("t"),
    )


def contract_from_yfinance(row, expiration, underlying):
    strike = _num(row.get("strike"))
    symbol = row.get("contractSymbol") or ""
    option_type = "call" if symbol[-9:-8].upper() == "C" else "put"
    bid, ask = _num(row.get("bid")), _num(row.get("ask"))
    iv = _num(row.get("impliedVolatility"))
    return OptionContract(
        symbol=symbol,
        underlying=underlying,
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        bid=bid,
        ask=ask,
        mid=_mid(bid, ask),
        last=_num(row.get("lastPrice")),
        volume=_num(row.get("volume")),
        open_interest=_num(row.get("openInterest")),
        iv=iv if (iv is not None and iv > 0) else None,
        iv_source="yfinance" if (iv is not None and iv > 0) else None,
        in_the_money=row.get("inTheMoney"),
    )


# ----------------------------------------------------------------------
# Enrichment: time to expiry, IV resolution (back-solve), recomputed Greeks
# ----------------------------------------------------------------------
def enrich(contract, spot, rate_fn, dividend_yield, now):
    """Fill time_to_expiry, rate, IV (back-solved if needed), and fresh Greeks."""
    T = _time_to_expiry(contract.expiration, now)
    contract.time_to_expiry = T
    r = rate_fn(T) if rate_fn else 0.0
    contract.rate_used = r
    q = dividend_yield or 0.0

    # IV source policy (Option C): use the provider's own IV when it is valid, and
    # compute IV from the market price via the engine only when the provider field
    # is missing or degenerate (e.g. bid=ask=0 with a near-zero IV over a close).
    # iv_source records which was used ('alpaca'/'yfinance' vs 'computed').
    provider_iv = contract.iv
    iv = None
    if provider_iv is not None and _IV_MIN_TRUST <= provider_iv <= _IV_MAX_PLAUSIBLE:
        iv = provider_iv  # keep the existing provider iv_source label
    else:
        price = contract.mid if contract.mid is not None else contract.last
        if spot and T > 0 and price and price > 0:
            solved = implied_vol(price, spot, contract.strike, T, r,
                                 contract.option_type, q)
            if solved is not None and 0 < solved <= _IV_MAX_PLAUSIBLE:
                iv, contract.iv_source = solved, "computed"
    if iv is None:
        contract.iv_source = None
    contract.iv = iv

    if iv and iv > 0 and spot and T > 0:
        g = bs_greeks(spot, contract.strike, T, r, iv, contract.option_type, q)
        contract.greeks = Greeks(
            delta=g["delta"], gamma=g["gamma"], vega=g["vega"],
            theta=g["theta"], rho=g["rho"],
        )
        contract.greeks_source = "recomputed"

    if contract.in_the_money is None and spot is not None:
        contract.in_the_money = (
            spot > contract.strike if contract.option_type == "call"
            else spot < contract.strike
        )
    return contract


def _reconcile_iv_by_strike(contracts, spot, dividend_yield):
    """
    Enforce call/put IV equality at each strike (put-call parity), using the
    out-of-the-money side as the reliable source. A deep-ITM option back-solves to
    a meaningless IV from a stale mid barely above intrinsic; the same-strike OTM
    option carries the trustworthy vol. The corrected side's Greeks are recomputed.
    """
    if not spot:
        return
    q = dividend_yield or 0.0
    groups = {}
    for c in contracts:
        groups.setdefault((c.strike, c.expiration), {})[c.option_type] = c
    for (strike, _exp), pair in groups.items():
        call, put = pair.get("call"), pair.get("put")
        if not (call and put):
            continue
        otm = put if strike <= spot else call
        itm = call if strike <= spot else put
        ref_iv = otm.iv if otm.iv else itm.iv
        if not ref_iv or itm.iv == ref_iv:
            continue
        itm.iv = ref_iv
        itm.iv_source = "parity"
        T = itm.time_to_expiry
        if T and T > 0 and itm.rate_used is not None:
            g = bs_greeks(spot, itm.strike, T, itm.rate_used, ref_iv,
                          itm.option_type, q)
            itm.greeks = Greeks(delta=g["delta"], gamma=g["gamma"], vega=g["vega"],
                                theta=g["theta"], rho=g["rho"])
            itm.greeks_source = "recomputed"


# ----------------------------------------------------------------------
# Chain builder with the source policy
# ----------------------------------------------------------------------
def build_chain(underlying, *, alpaca_snapshots=None, yfinance_by_expiration=None,
                spot, rate_fn, dividend_yield, dividend_source=None, now,
                iv_source="auto"):
    """
    Assemble a normalized OptionChain. alpaca_snapshots is the raw snapshots dict;
    yfinance_by_expiration maps an expiration date -> (calls_rows, puts_rows).
    """
    alpaca_snapshots = alpaca_snapshots or {}
    yfinance_by_expiration = yfinance_by_expiration or {}

    alpaca_contracts = {}
    if iv_source in ("auto", "alpaca"):
        for symbol, snap in alpaca_snapshots.items():
            c = contract_from_alpaca(symbol, snap)
            alpaca_contracts[_key(c.option_type, c.strike, c.expiration)] = c

    yfinance_contracts = {}
    if iv_source in ("auto", "yfinance"):
        for expiration, (calls, puts) in yfinance_by_expiration.items():
            for row in list(calls) + list(puts):
                c = contract_from_yfinance(row, expiration, underlying)
                if c.strike is None:
                    continue
                yfinance_contracts[_key(c.option_type, c.strike, c.expiration)] = c

    if iv_source == "alpaca":
        merged = alpaca_contracts
    elif iv_source == "yfinance":
        merged = yfinance_contracts
    else:
        merged = dict(alpaca_contracts)
        for key, ycon in yfinance_contracts.items():
            base = merged.get(key)
            if base is None:
                merged[key] = ycon
                continue
            # Fill Alpaca gaps from yfinance without overwriting live Alpaca values.
            if base.iv is None and ycon.iv is not None:
                base.iv, base.iv_source = ycon.iv, ycon.iv_source
            if base.volume is None:
                base.volume = ycon.volume
            if base.open_interest is None:
                base.open_interest = ycon.open_interest
            if base.last is None:
                base.last = ycon.last

    contracts = [
        enrich(c, spot, rate_fn, dividend_yield, now)
        for c in merged.values()
    ]
    _reconcile_iv_by_strike(contracts, spot, dividend_yield)
    contracts.sort(key=lambda c: (c.expiration, c.option_type, c.strike))
    expirations = sorted({c.expiration for c in contracts})

    return OptionChain(
        underlying=underlying,
        spot=spot,
        as_of=now,
        dividend_yield=dividend_yield,
        dividend_source=dividend_source,
        expirations=expirations,
        contracts=contracts,
    )
