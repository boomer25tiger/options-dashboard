"""
Verification for the Heston pricer (heston.py). No external benchmark table is
memorised; instead the semi-analytic price is pinned down three independent ways:

  1. Put-call parity, which must hold to machine precision.
  2. The zero-vol-of-vol limit, where Heston with v0 = theta collapses onto the
     already-verified Black-Scholes engine.
  3. An independent Heston Monte Carlo (Euler, full truncation), which must agree
     with the Fourier price to within Monte Carlo error.

Plus quadrature-convergence, arbitrage bounds, and the equity-skew sign.

Run:  python3 verify_heston.py
"""
import math
import sys

import numpy as np

from heston import heston_price, feller_ok
from pricing_engine import bs_price, implied_vol

_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


# A representative equity-index parameter set.
S, K, T, r, q = 100.0, 100.0, 1.0, 0.02, 0.0
V0, KAPPA, THETA, XI, RHO = 0.04, 1.5, 0.04, 0.30, -0.6


def heston_mc(S, K, T, r, q, v0, kappa, theta, xi, rho, otype="call",
              n_paths=200_000, n_steps=200, seed=12345):
    """Independent Euler / full-truncation Monte Carlo price and standard error."""
    rng = np.random.default_rng(seed)
    dt = T / n_steps
    sqrt_dt = math.sqrt(dt)
    log_s = np.full(n_paths, math.log(S))
    v = np.full(n_paths, v0)
    for _ in range(n_steps):
        z1 = rng.standard_normal(n_paths)
        z2 = rho * z1 + math.sqrt(1.0 - rho * rho) * rng.standard_normal(n_paths)
        v_pos = np.maximum(v, 0.0)
        log_s += (r - q - 0.5 * v_pos) * dt + np.sqrt(v_pos) * sqrt_dt * z1
        v += kappa * (theta - v_pos) * dt + xi * np.sqrt(v_pos) * sqrt_dt * z2
    s_t = np.exp(log_s)
    payoff = np.maximum(s_t - K, 0.0) if otype == "call" else np.maximum(K - s_t, 0.0)
    disc = math.exp(-r * T)
    price = disc * payoff.mean()
    stderr = disc * payoff.std(ddof=1) / math.sqrt(n_paths)
    return price, stderr


hr("Put-call parity")
call = heston_price(S, K, T, r, V0, KAPPA, THETA, XI, RHO, "call", q)
put = heston_price(S, K, T, r, V0, KAPPA, THETA, XI, RHO, "put", q)
parity_lhs = call - put
parity_rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
check("call - put = S e^-qT - K e^-rT", abs(parity_lhs - parity_rhs) < 1e-10,
      f"{parity_lhs:.10f} vs {parity_rhs:.10f}")


hr("Zero-vol-of-vol limit collapses onto Black-Scholes")
# With v0 = theta and a tiny xi, variance stays put at theta, so the price must
# match Black-Scholes at vol sqrt(theta).
flat = heston_price(S, K, T, r, THETA, KAPPA, THETA, 0.01, 0.0, "call", q)
bs = bs_price(S, K, T, r, math.sqrt(THETA), "call", q)
check("Heston(v0=theta, xi->0) matches Black-Scholes", abs(flat - bs) < 5e-3,
      f"heston {flat:.4f} vs bs {bs:.4f}")


hr("Independent Monte Carlo cross-check")
mc, se = heston_mc(S, K, T, r, q, V0, KAPPA, THETA, XI, RHO, "call")
analytic = call
check("Fourier price within 3 Monte Carlo standard errors of MC",
      abs(analytic - mc) < max(0.02, 3 * se),
      f"fourier {analytic:.4f} vs mc {mc:.4f} +/- {se:.4f}")


hr("Quadrature convergence")
lo = heston_price(S, K, T, r, V0, KAPPA, THETA, XI, RHO, "call", q, gl_n=96)
hi = heston_price(S, K, T, r, V0, KAPPA, THETA, XI, RHO, "call", q, gl_n=256)
check("128-point rule agrees with 256-point to 1e-4", abs(call - hi) < 1e-4,
      f"n128 {call:.6f} vs n256 {hi:.6f}")
check("96-point rule already close", abs(lo - hi) < 1e-3, f"n96 {lo:.6f}")


hr("Arbitrage bounds and positivity")
lb = max(0.0, S * math.exp(-q * T) - K * math.exp(-r * T))
ub = S * math.exp(-q * T)
check("call within [intrinsic forward, S e^-qT]", lb - 1e-9 <= call <= ub + 1e-9,
      f"{lb:.4f} <= {call:.4f} <= {ub:.4f}")
grid_ok = True
for kk in (70, 85, 100, 115, 130):
    for tt in (0.05, 0.5, 2.0):
        pr = heston_price(S, kk, tt, r, V0, KAPPA, THETA, XI, RHO, "call", q)
        if pr < -1e-8 or pr > S + 1e-6:
            grid_ok = False
check("prices finite and non-negative across a strike/maturity grid", grid_ok)


hr("Equity skew from negative correlation")
# rho < 0 must lift low-strike implied vol above high-strike (a downward skew).
def hiv(strike):
    p = heston_price(S, strike, T, r, V0, KAPPA, THETA, XI, RHO, "call", q)
    return implied_vol(p, S, strike, T, r, "call", q)

iv_low, iv_high = hiv(85), hiv(115)
check("implied vol at K=85 exceeds K=115 (downward skew)",
      iv_low is not None and iv_high is not None and iv_low > iv_high,
      f"iv(85) {iv_low:.4f} vs iv(115) {iv_high:.4f}")
check("Feller condition helper agrees with 2*kappa*theta vs xi^2",
      feller_ok(1.5, 0.04, 0.3) == (2 * 1.5 * 0.04 >= 0.3 ** 2))


hr("RESULT")
print(f"{len(_PASSES)} passed, {len(_FAILS)} failed")
sys.exit(1 if _FAILS else 0)
