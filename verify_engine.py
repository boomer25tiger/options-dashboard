"""
Verification of pricing_engine against published reference values.
Each check states its source and the expected number.
"""

from pricing_engine import (
    bs_price, bs_greeks, binomial_price, implied_vol,
    realized_vol, garman_klass_vol, prob_itm, breakeven_long_option,
    prob_profit_long_option
)

def check(label, got, expected, tol):
    status = "PASS" if abs(got - expected) < tol else "FAIL"
    print(f"[{status}] {label}")
    print(f"        expected ~{expected}, got {got:.6f}, diff {abs(got-expected):.2e}")

print("=" * 70)
print("BLACK-SCHOLES PRICE")
print("=" * 70)
# Reference: Hull, Options Futures and Other Derivatives.
# S=42, K=40, r=0.10, sigma=0.20, T=0.5, no dividend.
# Hull gives call = 4.759, put = 0.808.
c = bs_price(42, 40, 0.5, 0.10, 0.20, 'call')
p = bs_price(42, 40, 0.5, 0.10, 0.20, 'put')
check("Hull call (S=42,K=40,r=.10,sig=.20,T=.5)", c, 4.759, 0.01)
check("Hull put  (same inputs)", p, 0.808, 0.01)

# Put-call parity must hold exactly: C - P = S - K*exp(-rT)
import math
lhs = c - p
rhs = 42 - 40 * math.exp(-0.10 * 0.5)
check("Put-call parity C-P = S-Ke^(-rT)", lhs, rhs, 1e-9)

print()
print("=" * 70)
print("GREEKS")
print("=" * 70)
# Reference: standard at-the-money-ish case.
# S=100, K=100, r=0.05, sigma=0.20, T=1.0, no dividend.
# Widely published values: call delta ~0.6368, gamma ~0.01876,
# vega ~37.52 (per 1.00 vol), call theta ~ -6.414/yr, call rho ~ 53.23.
g = bs_greeks(100, 100, 1.0, 0.05, 0.20, 'call')
check("Call delta (S=K=100,r=.05,sig=.20,T=1)", g['delta'], 0.6368, 0.001)
check("Gamma", g['gamma'], 0.018762, 0.0005)
check("Vega (per 1.00 vol)", g['vega'], 37.524, 0.05)
check("Call theta (per year)", g['theta'], -6.414, 0.02)
check("Call rho (per 1.00 rate)", g['rho'], 53.232, 0.05)

# Put delta should equal call delta minus 1 (no dividend).
gp = bs_greeks(100, 100, 1.0, 0.05, 0.20, 'put')
check("Put delta = call delta - 1", gp['delta'], g['delta'] - 1.0, 1e-9)
# Gamma and vega identical for call and put.
check("Put gamma = call gamma", gp['gamma'], g['gamma'], 1e-12)
check("Put vega = call vega", gp['vega'], g['vega'], 1e-12)

print()
print("=" * 70)
print("BINOMIAL CONVERGENCE TO BLACK-SCHOLES (European)")
print("=" * 70)
# A European binomial with many steps must converge to the BS price.
bs_c = bs_price(100, 100, 1.0, 0.05, 0.20, 'call')
bin_c = binomial_price(100, 100, 1.0, 0.05, 0.20, 'call', steps=500, american=False)
check("European binomial call -> BS call", bin_c, bs_c, 0.02)

print()
print("=" * 70)
print("AMERICAN EARLY-EXERCISE PREMIUM")
print("=" * 70)
# An American put should be worth at least as much as the European put,
# and strictly more when early exercise has value (deep ITM put, positive r).
# S=90, K=100, r=0.05, sigma=0.20, T=1.0 -> ITM put.
eur_put = binomial_price(90, 100, 1.0, 0.05, 0.20, 'put', steps=500, american=False)
amer_put = binomial_price(90, 100, 1.0, 0.05, 0.20, 'put', steps=500, american=True)
print(f"        European put: {eur_put:.4f}")
print(f"        American put: {amer_put:.4f}")
print(f"        Early-exercise premium: {amer_put - eur_put:.4f}")
premium_positive = amer_put >= eur_put
print(f"[{'PASS' if premium_positive else 'FAIL'}] American put >= European put")
# American call on non-dividend stock equals European (never optimal to exercise early).
eur_call = binomial_price(110, 100, 1.0, 0.05, 0.20, 'call', steps=500, american=False)
amer_call = binomial_price(110, 100, 1.0, 0.05, 0.20, 'call', steps=500, american=True)
check("American call = European call (no dividend)", amer_call, eur_call, 0.01)

print()
print("=" * 70)
print("IMPLIED VOLATILITY ROUND-TRIP")
print("=" * 70)
# Price an option at a known vol, then recover that vol from the price.
true_sigma = 0.27
price = bs_price(105, 100, 0.75, 0.04, true_sigma, 'call')
recovered = implied_vol(price, 105, 100, 0.75, 0.04, 'call')
check("Recover sigma=0.27 from its own BS price", recovered, true_sigma, 1e-4)

true_sigma2 = 0.15
price2 = bs_price(95, 100, 0.30, 0.03, true_sigma2, 'put')
recovered2 = implied_vol(price2, 95, 100, 0.30, 0.03, 'put')
check("Recover sigma=0.15 (put) from its own price", recovered2, true_sigma2, 1e-4)

# IV below intrinsic should return None.
below = implied_vol(0.01, 150, 100, 1.0, 0.05, 'call')
print(f"[{'PASS' if below is None else 'FAIL'}] Price below intrinsic returns None (got {below})")

print()
print("=" * 70)
print("REALIZED VOLATILITY")
print("=" * 70)
# Construct a series with a known daily log return so annualized vol is predictable.
# If every day has the SAME return, sample stdev is 0.
flat = [100 * (1.01 ** i) for i in range(30)]
rv_flat = realized_vol(flat)
check("Constant-return series -> ~0 realized vol", rv_flat, 0.0, 1e-9)

# A series alternating up/down by a fixed factor has computable vol.
import math as _m
# Build returns of +0.01 and -0.01 alternating; sample stdev of {+.01,-.01,...}
alt = [100.0]
for i in range(200):
    factor = _m.exp(0.01) if i % 2 == 0 else _m.exp(-0.01)
    alt.append(alt[-1] * factor)
rv_alt = realized_vol(alt)
# returns are +/-0.01; population-ish stdev ~0.01, annualized ~0.01*sqrt(252)
expected_alt = 0.01 * _m.sqrt(252)
check("Alternating +/-1% returns -> annualized", rv_alt, expected_alt, 0.005)

print()
print("=" * 70)
print("GARMAN-KLASS REALIZED VOLATILITY")
print("=" * 70)
n_gk = 30
# No intraday movement at all -> zero GK vol.
flat_o = [100.0] * n_gk
check("Flat OHLC -> ~0 Garman-Klass vol",
      garman_klass_vol(flat_o, flat_o, flat_o, flat_o), 0.0, 1e-9)

# Constant daily range with flat closes: GK from the H/L range alone.
o2 = [100.0] * n_gk; c2 = [100.0] * n_gk
h2 = [101.0] * n_gk; l2 = [99.0] * n_gk
expected_gk = _m.sqrt(0.5 * _m.log(101 / 99) ** 2 * 252)
check("Constant-range OHLC -> Garman-Klass matches formula",
      garman_klass_vol(o2, h2, l2, c2), expected_gk, 1e-6)

# GK captures intraday range that close-to-close (flat closes) misses.
gk_intraday = garman_klass_vol(o2, h2, l2, c2)
cc_intraday = realized_vol(c2) or 0.0
print(f"        GK={gk_intraday:.4f} vs close-to-close={cc_intraday:.4f}")
print(f"[{'PASS' if gk_intraday > cc_intraday else 'FAIL'}] "
      f"GK captures intraday range that close-to-close misses")

print()
print("=" * 70)
print("PROBABILITY AND BREAKEVEN")
print("=" * 70)
# prob_itm for a call equals N(d2). For deep ITM call it approaches 1,
# for deep OTM approaches 0.
deep_itm = prob_itm(150, 100, 1.0, 0.05, 0.20, 'call')
deep_otm = prob_itm(50, 100, 1.0, 0.05, 0.20, 'call')
print(f"        Deep ITM call prob-ITM: {deep_itm:.4f} (should be near 1)")
print(f"        Deep OTM call prob-ITM: {deep_otm:.4f} (should be near 0)")
print(f"[{'PASS' if deep_itm > 0.95 else 'FAIL'}] Deep ITM call prob near 1")
print(f"[{'PASS' if deep_otm < 0.05 else 'FAIL'}] Deep OTM call prob near 0")

# Call and put prob-ITM at same strike must sum to 1 (complementary events).
call_p = prob_itm(100, 100, 1.0, 0.05, 0.20, 'call')
put_p = prob_itm(100, 100, 1.0, 0.05, 0.20, 'put')
check("Call prob-ITM + put prob-ITM = 1", call_p + put_p, 1.0, 1e-9)

# Breakeven checks.
be_call = breakeven_long_option(100, 5.0, 'call')
be_put = breakeven_long_option(100, 5.0, 'put')
check("Long call breakeven = K + premium", be_call, 105.0, 1e-12)
check("Long put breakeven = K - premium", be_put, 95.0, 1e-12)

print()
print("=" * 70)
print("Verification complete.")
print("=" * 70)
