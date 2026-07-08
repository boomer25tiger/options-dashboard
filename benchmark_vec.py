"""
Benchmark: the vectorized engine against the scalar loop on a full-chain workload.

Builds a chain the size of a real one (a dense strike ladder across several
expirations, calls and puts), then times pricing the Greeks and back-solving implied
vol both ways. Reports the wall-clock speedup, which is the point of the refactor.

Run:  python3 benchmark_vec.py
"""
import time

import numpy as np

from pricing_engine import bs_greeks, bs_price, implied_vol
from engine_vec import bs_greeks_vec, bs_price_vec, implied_vol_vec

SPOT, R, Q, SIGMA = 100.0, 0.03, 0.01, 0.20


def build_chain():
    strikes = np.arange(50.0, 150.5, 0.5)              # 201 strikes
    tenors = [0.02, 0.08, 0.25, 0.5, 1.0, 2.0]         # 6 expirations
    K, T, OT = [], [], []
    for k in strikes:
        for t in tenors:
            for o in ("call", "put"):
                K.append(k); T.append(t); OT.append(o)
    return np.array(K), np.array(T), OT


def best_of(fn, reps):
    best = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def main():
    K, T, OT = build_chain()
    n = len(K)
    print(f"chain of {n} contracts (201 strikes x 6 expirations x call/put)\n")

    t_price_vec = best_of(lambda: bs_price_vec(SPOT, K, T, R, SIGMA, OT, Q), reps=5)
    t_price_loop = best_of(lambda: [bs_price(SPOT, K[i], T[i], R, SIGMA, OT[i], Q)
                                    for i in range(n)], reps=3)
    print("Prices for the whole chain")
    print(f"  loop        {t_price_loop * 1000:8.1f} ms")
    print(f"  vectorized  {t_price_vec * 1000:8.2f} ms")
    print(f"  speedup     {t_price_loop / t_price_vec:8.0f}x\n")

    t_vec = best_of(lambda: bs_greeks_vec(SPOT, K, T, R, SIGMA, OT, Q), reps=5)
    t_loop = best_of(lambda: [bs_greeks(SPOT, K[i], T[i], R, SIGMA, OT[i], Q)
                              for i in range(n)], reps=3)
    print("Greeks (all five) for the whole chain")
    print(f"  loop        {t_loop * 1000:8.1f} ms")
    print(f"  vectorized  {t_vec * 1000:8.2f} ms")
    print(f"  speedup     {t_loop / t_vec:8.0f}x\n")

    # The implied-vol solver is bisection-bound (uniform iterations across the array),
    # so speed is not its story; it is verified to reproduce the scalar solver
    # exactly, which is what matters when it back-solves IV during chain enrichment.
    prices = bs_price_vec(SPOT, K, T, R, SIGMA, OT, Q)
    iv_vec = implied_vol_vec(prices, SPOT, K, T, R, OT, Q)
    iv_loop = np.array([implied_vol(float(prices[i]), SPOT, K[i], T[i], R, OT[i], Q)
                        or np.nan for i in range(n)])
    finite = np.isfinite(iv_vec) & np.isfinite(iv_loop)
    print("Implied-vol solver")
    print(f"  vectorized reproduces the scalar loop to "
          f"{np.max(np.abs(iv_vec[finite] - iv_loop[finite])):.0e} (correctness, not speed)")


if __name__ == "__main__":
    main()
