"""
Exercise the data layer against live SPY and print the values, with a handful of
correctness assertions. Secrets are never printed.

Run:  python3 check_data_layer.py
"""
import datetime as dt
import sys

from pricing_engine import bs_price, implied_vol, realized_vol
from backend.config import get_alpaca_credentials, mask
from backend.data import alpaca, dividends, normalize, rates, yfinance_client

TICKER = "SPY"
_PASSES = []
_FAILS = []


def check(label, condition, detail=""):
    (_PASSES if condition else _FAILS).append(label)
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def hr(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    print(f"Data-layer check for {TICKER} at {now.isoformat(timespec='seconds')}")
    print("Market is closed today (holiday); values reflect the last session.")

    # -- Credentials ---------------------------------------------------
    hr("CREDENTIALS")
    cred = get_alpaca_credentials()
    print(f"  Alpaca key id: {mask(cred.key_id)}  (secret present, not shown)")

    # -- Alpaca snapshots ---------------------------------------------
    hr("ALPACA SNAPSHOTS")
    snaps = alpaca.get_option_snapshots(
        TICKER,
        expiration_gte=today,
        expiration_lte=today + dt.timedelta(days=45),
        feed="indicative",
        limit=100,
    )
    n_alpaca_iv = sum(1 for s in snaps.values() if s.get("impliedVolatility") is not None)
    check("Alpaca returned option snapshots", len(snaps) > 0,
          f"{len(snaps)} contracts, {n_alpaca_iv} with Alpaca IV")

    # -- yfinance chain ------------------------------------------------
    hr("YFINANCE CHAIN")
    exps = yfinance_client.get_expirations(TICKER)
    check("yfinance returned expirations", len(exps) > 0, f"{len(exps)} expirations")
    nearest = exps[:2]
    yf_by_exp = {}
    for exp_str in nearest:
        calls, puts = yfinance_client.get_option_chain(TICKER, exp_str)
        exp_date = dt.date.fromisoformat(exp_str)
        yf_by_exp[exp_date] = (calls, puts)
        iv_present = sum(1 for r in calls if r.get("impliedVolatility"))
        check(f"yfinance chain {exp_str} has IV", iv_present > 0,
              f"{len(calls)} calls, {iv_present} with IV")

    # -- Spot ----------------------------------------------------------
    hr("SPOT")
    spot = yfinance_client.get_spot(TICKER)
    check("spot price looks sane", spot is not None and 50 < spot < 5000,
          f"spot={spot}")

    # -- Risk-free curve (FRED primary, Yahoo fallback) ----------------
    hr("RISK-FREE CURVE")
    rate_fn, rate_source, tsy, rate_asof = rates.get_rate_curve()
    print(f"  source: {rate_source}   as_of: {rate_asof}   points: {len(tsy)}")
    print(f"  tenor(y) -> rate: { {k: round(v, 4) for k, v in sorted(tsy.items())} }")
    samples = {t: round(rate_fn(t), 4) for t in (0.1, 1.0, 7.0, 20.0)}
    print(f"  interpolated rate at [0.1, 1, 7, 20]y: {samples}")
    check("rate curve obtained (FRED or fallback)",
          rate_source in ("fred", "yahoo") and len(tsy) >= 2,
          f"source={rate_source}, {len(tsy)} points")
    check("interpolated rates in a sane band",
          all(-0.01 < rate_fn(t) < 0.20 for t in (0.05, 0.5, 3, 12, 40)))
    mid_t = 6.0
    below = [k for k in tsy if k <= mid_t]
    above = [k for k in tsy if k >= mid_t]
    if below and above:
        lo, hi = max(below), min(above)
        if lo != hi:
            r_mid = rate_fn(mid_t)
            check("interpolated 6y rate lies between its bracketing tenors",
                  min(tsy[lo], tsy[hi]) - 1e-9 <= r_mid <= max(tsy[lo], tsy[hi]) + 1e-9,
                  f"{round(tsy[lo],4)} <= {round(r_mid,4)} <= {round(tsy[hi],4)}")

    # -- Dividend yield ------------------------------------------------
    hr("DIVIDEND YIELD")
    q, q_src = dividends.resolve_dividend_yield(TICKER)
    check("dividend yield in a sane band", 0.0 <= q < 0.05,
          f"q={round(q, 4)} (source: {q_src})")

    # -- Realized vol --------------------------------------------------
    hr("REALIZED VOLATILITY")
    bars = alpaca.get_stock_bars(TICKER, start=today - dt.timedelta(days=150))
    closes = [b["c"] for b in bars]
    print(f"  daily closes fetched: {len(closes)}")
    rv = {w: realized_vol(closes, window=w) for w in (10, 20, 30, 60)}
    print("  realized vol (annualized): "
          + ", ".join(f"{w}d={round(v, 4) if v else None}" for w, v in rv.items()))
    check("realized vol computed for all windows",
          all(v is not None and 0 < v < 2 for v in rv.values()))

    # -- Normalized chain (auto) --------------------------------------
    hr("NORMALIZED CHAIN (auto source, Greeks recomputed vs current clock)")
    chain = normalize.build_chain(
        TICKER,
        alpaca_snapshots=snaps,
        yfinance_by_expiration=yf_by_exp,
        spot=spot,
        rate_fn=rate_fn,
        dividend_yield=q,
        dividend_source=q_src,
        now=now,
        iv_source="auto",
    )
    contracts = chain.contracts
    with_iv = [c for c in contracts if c.iv]
    with_greeks = [c for c in contracts if c.greeks_source == "recomputed"]
    iv_src_counts = {}
    for c in with_iv:
        iv_src_counts[c.iv_source] = iv_src_counts.get(c.iv_source, 0) + 1
    print(f"  contracts: {len(contracts)} across {len(chain.expirations)} expirations")
    print(f"  with IV: {len(with_iv)}  (by source: {iv_src_counts})")
    print(f"  with recomputed Greeks: {len(with_greeks)}")

    check("normalized contracts present", len(contracts) > 0)
    check("most contracts have IV and Greeks",
          len(with_greeks) >= 0.5 * len(contracts),
          f"{len(with_greeks)}/{len(contracts)}")

    # Sample a near-the-money call to eyeball the numbers.
    calls_atm = sorted(
        (c for c in contracts if c.option_type == "call" and c.greeks.delta is not None),
        key=lambda c: abs(c.strike - (spot or c.strike)),
    )
    if calls_atm:
        c = calls_atm[0]
        g = c.greeks
        print(f"\n  Near-the-money call {c.symbol}")
        print(f"    strike={c.strike}  exp={c.expiration}  T={round(c.time_to_expiry,4)}y")
        print(f"    bid/ask={c.bid}/{c.ask}  mid={c.mid}  IV={round(c.iv,4)} "
              f"({c.iv_source})  r={round(c.rate_used,4)}")
        print(f"    delta={round(g.delta,4)} gamma={round(g.gamma,5)} "
              f"vega={round(g.vega,4)} theta/yr={round(g.theta,3)} rho={round(g.rho,4)}")

    # Greek sanity across the chain.
    call_deltas_ok = all(
        -0.001 <= c.greeks.delta <= 1.001
        for c in contracts if c.option_type == "call" and c.greeks.delta is not None
    )
    put_deltas_ok = all(
        -1.001 <= c.greeks.delta <= 0.001
        for c in contracts if c.option_type == "put" and c.greeks.delta is not None
    )
    gamma_ok = all(
        c.greeks.gamma >= -1e-9
        for c in contracts if c.greeks.gamma is not None
    )
    check("call deltas within [0, 1]", call_deltas_ok)
    check("put deltas within [-1, 0]", put_deltas_ok)
    check("gammas non-negative", gamma_ok)

    # -- Engine round-trip through the layer's back-solve --------------
    hr("IV BACK-SOLVE ROUND-TRIP")
    S, K, T, r, sig = 500.0, 505.0, 0.25, 0.04, 0.22
    synth_price = bs_price(S, K, T, r, sig, "call", 0.0)
    solved = implied_vol(synth_price, S, K, T, r, "call", 0.0)
    check("back-solved IV recovers the input sigma",
          solved is not None and abs(solved - sig) < 1e-3,
          f"input {sig}, recovered {round(solved, 6) if solved else None}")

    # -- Summary -------------------------------------------------------
    hr("SUMMARY")
    print(f"  {len(_PASSES)} passed, {len(_FAILS)} failed")
    if _FAILS:
        print("  FAILED: " + ", ".join(_FAILS))
    sys.exit(0 if not _FAILS else 1)


if __name__ == "__main__":
    main()
