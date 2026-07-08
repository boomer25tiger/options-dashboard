"""
Check the multi-leg strategy math against known analytic results. No network is
needed; everything runs on a synthetic market context.

Run:  python3 check_strategy.py
"""
import datetime as dt
import sys

from pricing_engine import bs_greeks, bs_price, prob_profit_long_option
from backend.strategy import (
    Leg, MarketContext, leg_breakdown, net_cost,
    payoff_curve, position_greeks, prob_of_profit, summarize, time_to_expiry,
)

_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def approx(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


# Synthetic context: S=100, r=5% flat, q=0, sigma=0.20, ~0.5y to expiry.
SPOT = 100.0
SIGMA = 0.20
R = 0.05
NOW = dt.datetime(2026, 1, 2, 15, 0, 0, tzinfo=dt.timezone.utc)
EXP = dt.date(2026, 7, 3)
CTX = MarketContext(spot=SPOT, now=NOW, rate_fn=lambda T: R, dividend_yield=0.0)
T = time_to_expiry(EXP, NOW)
MULT = 100


def call_leg(K, qty):
    return Leg("call", qty, strike=K, expiration=EXP, sigma=SIGMA)


def put_leg(K, qty):
    return Leg("put", qty, strike=K, expiration=EXP, sigma=SIGMA)


def price(kind, K):
    return bs_price(SPOT, K, T, R, SIGMA, kind, 0.0)


def main():
    print(f"Synthetic context: S={SPOT}, r={R}, q=0, sigma={SIGMA}, T={round(T,4)}y")

    # -- Long call ------------------------------------------------------
    hr("LONG CALL")
    prem = price("call", 100)
    legs = [call_leg(100, +1)]
    s = summarize(legs, CTX)
    check("breakeven = K + premium",
          approx(s["breakevens"][0], 100 + prem, 1e-3),
          f"{round(s['breakevens'][0],4)} vs {round(100+prem,4)}")
    check("max profit unbounded", s["max_profit"] is None)
    check("max loss = -premium * 100", approx(s["max_loss"], -prem * MULT, 1e-2),
          f"{round(s['max_loss'],2)} vs {round(-prem*MULT,2)}")
    check("net cost = +premium * 100 (debit)", approx(s["net_cost"], prem * MULT, 1e-6))
    dc = bs_greeks(SPOT, 100, T, R, SIGMA, "call", 0.0)["delta"]
    check("position delta = 100 * call delta",
          approx(s["greeks"]["delta"], MULT * dc, 1e-6))

    # -- Long put -------------------------------------------------------
    hr("LONG PUT")
    pprem = price("put", 100)
    legs = [put_leg(100, +1)]
    s = summarize(legs, CTX)
    check("breakeven = K - premium",
          approx(s["breakevens"][0], 100 - pprem, 1e-3))
    check("max profit = (K - premium) * 100 (bounded at S=0)",
          approx(s["max_profit"], (100 - pprem) * MULT, 1e-2),
          f"{round(s['max_profit'],2)} vs {round((100-pprem)*MULT,2)}")
    check("max loss = -premium * 100", approx(s["max_loss"], -pprem * MULT, 1e-2))

    # -- Bull call spread ----------------------------------------------
    hr("BULL CALL SPREAD (long 100 call / short 110 call)")
    c1, c2 = price("call", 100), price("call", 110)
    debit = c1 - c2
    legs = [call_leg(100, +1), call_leg(110, -1)]
    s = summarize(legs, CTX)
    check("breakeven = lower K + net debit",
          approx(s["breakevens"][0], 100 + debit, 1e-3),
          f"{round(s['breakevens'][0],4)} vs {round(100+debit,4)}")
    check("max profit = (width - debit) * 100",
          approx(s["max_profit"], (10 - debit) * MULT, 1e-2),
          f"{round(s['max_profit'],2)} vs {round((10-debit)*MULT,2)}")
    check("max loss = -debit * 100", approx(s["max_loss"], -debit * MULT, 1e-2))
    check("both bounded", s["max_profit"] is not None and s["max_loss"] is not None)
    d1 = bs_greeks(SPOT, 100, T, R, SIGMA, "call", 0.0)["delta"]
    d2 = bs_greeks(SPOT, 110, T, R, SIGMA, "call", 0.0)["delta"]
    check("net delta = 100 * (delta_long - delta_short)",
          approx(s["greeks"]["delta"], MULT * (d1 - d2), 1e-6))

    # -- Short straddle -------------------------------------------------
    hr("SHORT STRADDLE (short 100 call + short 100 put)")
    legs = [call_leg(100, -1), put_leg(100, -1)]
    s = summarize(legs, CTX)
    total_prem = price("call", 100) + price("put", 100)
    check("max profit = total premium * 100 (at S=K)",
          approx(s["max_profit"], total_prem * MULT, 1e-2),
          f"{round(s['max_profit'],2)} vs {round(total_prem*MULT,2)}")
    check("max loss unbounded", s["max_loss"] is None)
    bes = sorted(s["breakevens"])
    check("two breakevens ~ K +/- premium", len(bes) == 2
          and approx(bes[0], 100 - total_prem, 1e-2)
          and approx(bes[1], 100 + total_prem, 1e-2),
          f"{[round(b,3) for b in bes]}")

    # -- Synthetic long (call - put, same strike) => Greeks of stock ----
    hr("SYNTHETIC LONG (long 100 call + short 100 put)")
    legs = [call_leg(100, +1), put_leg(100, -1)]
    g = position_greeks(legs, CTX)
    check("delta = +100 (one synthetic share x100)", approx(g["delta"], 100.0, 1e-6),
          f"delta={round(g['delta'],6)}")
    check("gamma ~ 0", abs(g["gamma"]) < 1e-9, f"gamma={g['gamma']:.2e}")
    check("vega ~ 0", abs(g["vega"]) < 1e-9, f"vega={g['vega']:.2e}")

    # -- Probability of profit cross-checks vs the engine ---------------
    hr("PROBABILITY OF PROFIT (vs engine single-option formula)")
    prem = price("call", 100)
    pop_call = prob_of_profit([call_leg(100, +1)], CTX)
    eng_call = prob_profit_long_option(SPOT, 100, T, R, SIGMA, "call", prem, 0.0)
    check("long-call PoP == engine.prob_profit_long_option",
          approx(pop_call, eng_call, 1e-4),
          f"{round(pop_call,5)} vs {round(eng_call,5)}")
    pprem = price("put", 100)
    pop_put = prob_of_profit([put_leg(100, +1)], CTX)
    eng_put = prob_profit_long_option(SPOT, 100, T, R, SIGMA, "put", pprem, 0.0)
    check("long-put PoP == engine.prob_profit_long_option",
          approx(pop_put, eng_put, 1e-4),
          f"{round(pop_put,5)} vs {round(eng_put,5)}")

    # -- Iron condor (bounded both sides) ------------------------------
    hr("IRON CONDOR (long90p short95p short105c long110c)")
    legs = [put_leg(90, +1), put_leg(95, -1), call_leg(105, -1), call_leg(110, +1)]
    s = summarize(legs, CTX)
    check("max profit bounded and positive",
          s["max_profit"] is not None and s["max_profit"] > 0,
          f"max_profit={round(s['max_profit'],2) if s['max_profit'] is not None else None}")
    check("max loss bounded and negative",
          s["max_loss"] is not None and s["max_loss"] < 0,
          f"max_loss={round(s['max_loss'],2) if s['max_loss'] is not None else None}")
    check("two breakevens between the inner strikes",
          len(s["breakevens"]) == 2
          and 90 < s["breakevens"][0] < 100 < s["breakevens"][1] < 110,
          f"{[round(b,3) for b in sorted(s['breakevens'])]}")
    pop = s["prob_of_profit"]
    check("PoP is a probability in (0, 1)", pop is not None and 0 < pop < 1,
          f"PoP={round(pop,4) if pop is not None else None}")

    # -- Time-aware payoff: value >= intrinsic before expiry, = at expiry
    hr("TIME-AWARE PAYOFF")
    legs = [call_leg(100, +1)]
    mid_dt = NOW + dt.timedelta(days=60)
    xs, curves = payoff_curve(legs, CTX, [mid_dt, dt.datetime(EXP.year, EXP.month,
                              EXP.day, 20, tzinfo=dt.timezone.utc)], points=51)
    # find index nearest S=100
    i = min(range(len(xs)), key=lambda k: abs(xs[k] - 100))
    prem = price("call", 100)
    exp_dt = dt.datetime(EXP.year, EXP.month, EXP.day, 20, tzinfo=dt.timezone.utc)
    pnl_mid = curves[mid_dt][i]
    pnl_exp = curves[exp_dt][i]
    check("at expiry, ATM long call P&L = -premium*100 (intrinsic 0)",
          approx(pnl_exp, -prem * MULT, 1e-2),
          f"{round(pnl_exp,2)} vs {round(-prem*MULT,2)}")
    check("before expiry, ATM value has time premium (P&L > expiry P&L)",
          pnl_mid > pnl_exp + 1.0, f"mid={round(pnl_mid,2)} > exp={round(pnl_exp,2)}")

    # -- Leg breakdown reconciles to the aggregate ---------------------
    hr("LEG BREAKDOWN RECONCILES TO AGGREGATE")
    legs = [call_leg(100, +1), call_leg(110, -1), put_leg(95, -1)]
    rows = leg_breakdown(legs, CTX)
    pg = position_greeks(legs, CTX)  # native units
    check("leg costs sum to net cost",
          approx(sum(r["cost"] for r in rows), net_cost(legs, CTX), 1e-6))
    check("leg delta contributions sum to net delta",
          approx(sum(r["greeks"]["delta"] for r in rows), pg["delta"], 1e-6))
    check("leg vega (display) sums to net vega / 100",
          approx(sum(r["greeks"]["vega"] for r in rows), pg["vega"] / 100.0, 1e-6))
    check("leg theta (display) sums to net theta / 365",
          approx(sum(r["greeks"]["theta"] for r in rows), pg["theta"] / 365.0, 1e-6))

    # -- Summary --------------------------------------------------------
    hr("SUMMARY")
    print(f"  {len(_PASSES)} passed, {len(_FAILS)} failed")
    if _FAILS:
        print("  FAILED: " + ", ".join(_FAILS))
    sys.exit(0 if not _FAILS else 1)


if __name__ == "__main__":
    main()
