"""
Verification for the delta-hedging simulation (backend/hedging.py).

Checks the economics rather than a table of numbers:
  - Flat path: a long option just bleeds its premium.
  - Vol spread sets the sign: hedging at an implied vol below realized makes the
    long position money on average, above realized loses it.
  - The gamma gain plus theta bleed reconstructs the total P&L.
  - A short position is the mirror of the long.

Run:  python3 check_hedging.py
"""
import math
import sys

import numpy as np

from backend.hedging import simulate

_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def gbm_path(s0, sigma, days, seed, r=0.0, steps_per_year=252):
    rng = np.random.default_rng(seed)
    dt = 1.0 / steps_per_year
    rets = rng.normal((r - 0.5 * sigma * sigma) * dt, sigma * math.sqrt(dt), days)
    return (s0 * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))).tolist()


def mean_long_pnl(sigma_real, sigma_imp, seeds):
    vals = []
    for sd in seeds:
        res = simulate(gbm_path(100.0, sigma_real, 30, sd), sigma_imp, r=0.0,
                       option_type="call", position=1)
        vals.append(res["summary"]["total_pnl"])
    return sum(vals) / len(vals)


hr("Flat path bleeds the premium")
flat = simulate([100.0] * 31, 0.20, r=0.0, q=0.0, option_type="call", position=1)
s = flat["summary"]
check("long option with no moves loses its premium",
      s["total_pnl"] < 0 and abs(s["total_pnl"] + s["entry_premium"]) < 0.05,
      f"pnl {s['total_pnl']} vs -premium {-s['entry_premium']}")
check("realized vol of a flat path is zero", s["realized_vol"] == 0.0)


hr("Volatility spread sets the sign of the hedged P&L")
high = mean_long_pnl(0.40, 0.20, range(40))   # path moves more than priced
low = mean_long_pnl(0.08, 0.20, range(40))    # path moves less than priced
check("realized above implied: long delta-hedge profits on average", high > 0,
      f"mean pnl {high:.2f}")
check("realized below implied: long delta-hedge loses on average", low < 0,
      f"mean pnl {low:.2f}")


hr("Gamma gain and theta bleed reconstruct the total")
path = gbm_path(100.0, 0.25, 30, seed=7)
res = simulate(path, 0.25, r=0.0, option_type="call", position=1)
s = res["summary"]
approx = s["gamma_pnl_total"] + s["theta_pnl_total"]
check("total P&L is close to gamma plus theta",
      abs(s["total_pnl"] - approx) < 0.12 * abs(s["entry_premium"]) + 2.0,
      f"total {s['total_pnl']} vs gamma+theta {approx:.2f}")
check("long option is long gamma and pays theta",
      s["gamma_pnl_total"] > 0 and s["theta_pnl_total"] < 0,
      f"gamma {s['gamma_pnl_total']} theta {s['theta_pnl_total']}")


hr("Short mirrors long, and structure")
long_res = simulate(path, 0.25, r=0.0, position=1)
short_res = simulate(path, 0.25, r=0.0, position=-1)
check("short P&L is the negative of long P&L",
      abs(long_res["summary"]["total_pnl"] + short_res["summary"]["total_pnl"]) < 0.05)
check("one step per day plus the open", len(res["steps"]) == 31)
check("portfolio starts at zero", res["steps"][0]["cum_pnl"] == 0.0)

check("too few closes returns None", simulate([100.0, 101.0], 0.2, 0.0) is None)
check("non-positive implied vol returns None", simulate([100.0, 101.0, 102.0], 0.0, 0.0) is None)


hr("RESULT")
print(f"{len(_PASSES)} passed, {len(_FAILS)} failed")
sys.exit(1 if _FAILS else 0)
