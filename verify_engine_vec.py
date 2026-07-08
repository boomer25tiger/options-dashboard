"""
Verification for the vectorized engine (engine_vec.py).

The scalar engine in pricing_engine.py is the reference. This prices a grid of
contracts both ways and checks the vectorized results match element for element:
price and Greeks to machine precision, implied vol to solver tolerance, and the
NaN pattern of implied_vol_vec lined up with the scalar solver's None.

Run:  python3 verify_engine_vec.py
"""
import itertools
import math
import sys

import numpy as np

from pricing_engine import bs_greeks, bs_price, implied_vol
from engine_vec import bs_greeks_vec, bs_price_vec, implied_vol_vec

_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


SPOT, R, Q = 100.0, 0.03, 0.01
rows = list(itertools.product(
    [70, 80, 90, 95, 100, 105, 110, 120, 130],   # strikes
    [0.05, 0.25, 0.5, 1.0, 2.0],                  # tenors
    [0.10, 0.20, 0.35],                           # vols
    ["call", "put"],
))
K = np.array([x[0] for x in rows], float)
T = np.array([x[1] for x in rows], float)
SIG = np.array([x[2] for x in rows], float)
OT = [x[3] for x in rows]
print(f"grid of {len(rows)} contracts")


hr("Price matches the scalar engine element for element")
price_vec = bs_price_vec(SPOT, K, T, R, SIG, OT, Q)
price_scalar = np.array([bs_price(SPOT, k, t, R, s, o, Q) for k, t, s, o in rows])
check("max |price_vec - price_scalar| < 1e-10",
      float(np.max(np.abs(price_vec - price_scalar))) < 1e-10,
      f"max diff {np.max(np.abs(price_vec - price_scalar)):.2e}")


hr("Greeks match the scalar engine")
gv = bs_greeks_vec(SPOT, K, T, R, SIG, OT, Q)
for name in ("delta", "gamma", "vega", "theta", "rho"):
    scal = np.array([bs_greeks(SPOT, k, t, R, s, o, Q)[name] for k, t, s, o in rows])
    diff = float(np.max(np.abs(gv[name] - scal)))
    check(f"max |{name}_vec - {name}_scalar| < 1e-9", diff < 1e-9, f"max diff {diff:.2e}")


hr("Implied vol matches, and round-trips the input vol")
iv_vec = implied_vol_vec(price_vec, SPOT, K, T, R, OT, Q)
iv_scalar = np.array([implied_vol(p, SPOT, k, t, R, o, Q)
                      for p, (k, t, s, o) in zip(price_vec, rows)], dtype=object)
iv_scalar = np.array([np.nan if v is None else v for v in iv_scalar], dtype=float)
finite = np.isfinite(iv_vec) & np.isfinite(iv_scalar)
check("vectorized IV agrees with the scalar solver",
      float(np.max(np.abs(iv_vec[finite] - iv_scalar[finite]))) < 1e-4,
      f"max diff {np.max(np.abs(iv_vec[finite] - iv_scalar[finite])):.2e}")
# Where vega is meaningful the shared bisection recovers the input vol tightly. A
# deep in/out or ultra-short contract has near-zero vega, so a price tolerance maps
# to a loose vol for the scalar solver just the same (both agree, above).
vega = gv["vega"]
priced = finite & (vega > 1.0)
check("recovered vol round-trips the input vol where vega is meaningful",
      float(np.max(np.abs(iv_vec[priced] - SIG[priced]))) < 1e-4,
      f"max diff {np.max(np.abs(iv_vec[priced] - SIG[priced])):.2e}")
check("solvable mask matches the scalar None pattern",
      bool(np.array_equal(np.isfinite(iv_vec), np.isfinite(iv_scalar))))


hr("Edge cases line up with the scalar engine")
# Expiry and zero vol.
check("expired call price equals intrinsic",
      abs(float(bs_price_vec(100.0, 90.0, 0.0, R, 0.2, "call", Q)) - 10.0) < 1e-12)
check("zero-vol put matches the scalar engine",
      abs(float(bs_price_vec(100.0, 110.0, 1.0, R, 0.0, "put", Q))
          - bs_price(100.0, 110.0, 1.0, R, 0.0, "put", Q)) < 1e-12)
gv_edge = bs_greeks_vec(100.0, 100.0, 0.0, R, 0.2, "call", Q)
check("Greeks are NaN at expiry, as in the scalar engine",
      all(math.isnan(float(gv_edge[g])) for g in ("delta", "gamma", "vega", "theta", "rho")))
check("price below intrinsic gives NaN implied vol",
      math.isnan(float(implied_vol_vec(0.5, 100.0, 80.0, 1.0, R, "call", Q))))


hr("RESULT")
print(f"{len(_PASSES)} passed, {len(_FAILS)} failed")
sys.exit(1 if _FAILS else 0)
