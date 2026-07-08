"""
Verification for the Monte Carlo pricer (backend/montecarlo.py).

Anchored to values it must reproduce:
  - Vanilla European: the 95% interval brackets Black-Scholes, and put-call parity
    holds across the two MC prices.
  - Convergence: the interval narrows toward Black-Scholes as paths grow.
  - Geometric Asian: matches its closed-form (continuous-averaging) price.
  - Barrier: knock-in plus knock-out equals the vanilla, and a knock-out is worth
    less than the vanilla.

Run:  python3 check_montecarlo.py
"""
import math
import sys

from backend.montecarlo import (
    european_convergence, price_asian, price_barrier, price_european, sample_paths,
)
from pricing_engine import bs_price

_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def _N(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def geo_asian_call(S, K, T, r, sigma, q):
    """Continuous geometric-average Asian call, closed form (lognormal average)."""
    m = math.log(S) + 0.5 * (r - q - 0.5 * sigma * sigma) * T
    s = sigma * math.sqrt(T / 3.0)
    d1 = (m - math.log(K) + s * s) / s
    d2 = d1 - s
    return math.exp(-r * T) * (math.exp(m + 0.5 * s * s) * _N(d1) - K * _N(d2))


S, K, T, r, sigma, q = 100.0, 100.0, 1.0, 0.03, 0.20, 0.0


hr("Vanilla European brackets Black-Scholes")
call = price_european(S, K, T, r, sigma, "call", q, n_paths=400_000)
bs_call = bs_price(S, K, T, r, sigma, "call", q)
check("call 95% interval contains Black-Scholes",
      call["ci_low"] <= bs_call <= call["ci_high"],
      f"{call['ci_low']:.3f} <= {bs_call:.3f} <= {call['ci_high']:.3f}")
put = price_european(S, K, T, r, sigma, "put", q, n_paths=400_000)
bs_put = bs_price(S, K, T, r, sigma, "put", q)
check("put 95% interval contains Black-Scholes",
      put["ci_low"] <= bs_put <= put["ci_high"],
      f"{put['ci_low']:.3f} <= {bs_put:.3f} <= {put['ci_high']:.3f}")
parity = (call["price"] - put["price"]) - (S * math.exp(-q * T) - K * math.exp(-r * T))
check("MC put-call parity holds", abs(parity) < 0.05, f"residual {parity:.4f}")


hr("Convergence toward Black-Scholes")
conv = european_convergence(S, K, T, r, sigma, "call", q)
w_first = conv[0]["ci_high"] - conv[0]["ci_low"]
w_last = conv[-1]["ci_high"] - conv[-1]["ci_low"]
check("interval narrows sharply with more paths", w_last < 0.25 * w_first,
      f"width {w_first:.3f} -> {w_last:.3f}")
check("converged price sits near Black-Scholes", abs(conv[-1]["price"] - bs_call) < 0.10,
      f"mc {conv[-1]['price']:.3f} vs bs {bs_call:.3f}")


hr("Geometric Asian matches its closed form")
ga = price_asian(S, K, T, r, sigma, "call", q, average="geometric",
                 n_paths=120_000, n_steps=252)
ga_analytic = geo_asian_call(S, K, T, r, sigma, q)
check("geometric Asian MC matches the analytic price",
      abs(ga["price"] - ga_analytic) < max(0.03, 4 * ga["stderr"]),
      f"mc {ga['price']:.3f} vs analytic {ga_analytic:.3f} (se {ga['stderr']:.3f})")
aa = price_asian(S, K, T, r, sigma, "call", q, average="arithmetic",
                 n_paths=120_000, n_steps=100)
check("arithmetic Asian call is cheaper than the vanilla",
      aa["price"] < call["price"], f"asian {aa['price']:.3f} vs vanilla {call['price']:.3f}")


hr("Barrier in-out parity")
ki = price_barrier(S, K, T, r, sigma, 120.0, "up-and-in", "call", q,
                   n_paths=120_000, n_steps=150)
ko = price_barrier(S, K, T, r, sigma, 120.0, "up-and-out", "call", q,
                   n_paths=120_000, n_steps=150)
check("up-and-in plus up-and-out equals the vanilla",
      abs((ki["price"] + ko["price"]) - bs_call) < 0.12,
      f"in {ki['price']:.3f} + out {ko['price']:.3f} vs vanilla {bs_call:.3f}")
check("knock-out is worth less than the vanilla", ko["price"] < bs_call)
check("knock probability is between 0 and 1", 0.0 < ki["knock_probability"] < 1.0,
      f"{ki['knock_probability']:.3f}")


hr("Guards")
check("expired option returns intrinsic",
      price_european(100.0, 90.0, 0.0, r, sigma, "call")["price"] == 10.0)
check("Asian with no steps returns None", price_asian(S, K, T, r, sigma, n_steps=0) is None)
check("barrier with non-positive level returns None",
      price_barrier(S, K, T, r, sigma, 0.0, "up-and-out") is None)


hr("Sample paths for the visualization")
sp = sample_paths(100.0, 1.0, 0.03, 0.20, 0.0, n_paths=50, n_steps=40,
                  barrier=130.0, barrier_type="up-and-out")
check("returns the requested number of paths", len(sp["paths"]) == 50)
check("each path has n_steps+1 points", len(sp["paths"][0]) == 41 and len(sp["times"]) == 41)
check("every path starts at spot", all(abs(row[0] - 100.0) < 1e-6 for row in sp["paths"]))
check("breach flags are present with a barrier",
      sp["breached"] is not None and len(sp["breached"]) == 50)
check("breach flags align with reaching the barrier",
      all((max(row) >= 129.5) if sp["breached"][i] else (max(row) <= 130.5)
          for i, row in enumerate(sp["paths"])))
sp_plain = sample_paths(100.0, 1.0, 0.03, 0.20, n_paths=10, n_steps=20)
check("no barrier means no breach flags", sp_plain["breached"] is None)
check("degenerate inputs return None", sample_paths(100.0, 0.0, 0.03, 0.20) is None)


hr("RESULT")
print(f"{len(_PASSES)} passed, {len(_FAILS)} failed")
sys.exit(1 if _FAILS else 0)
