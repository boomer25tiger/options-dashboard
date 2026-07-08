"""
Monte Carlo option pricer.

Simulation-based pricing under risk-neutral geometric Brownian motion, added beside
the closed-form (Black-Scholes), tree (binomial), and stochastic-vol (Heston)
methods. On a vanilla European the four agree, which is the point of showing it. It
also prices path-dependent options the closed forms cannot: arithmetic and geometric
Asians (payoff on the average price) and knock-in / knock-out barriers.

NumPy-vectorized, since the method is inherently array work and NumPy is already a
dependency (and the next planned extension is engine vectorization). Each price
carries its standard error and a 95% confidence interval, and antithetic variates
tighten the estimate. A fixed default seed keeps a displayed price reproducible.
"""
import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np


def _terminal(S: float, T: float, r: float, sigma: float, q: float, z: np.ndarray) -> np.ndarray:
    return S * np.exp((r - q - 0.5 * sigma * sigma) * T + sigma * math.sqrt(T) * z)


def _payoff(s: np.ndarray, K: float, option_type: str) -> np.ndarray:
    return np.maximum(s - K, 0.0) if option_type == "call" else np.maximum(K - s, 0.0)


def _summary(disc_payoff: np.ndarray) -> Dict[str, Any]:
    price = float(disc_payoff.mean())
    stderr = float(disc_payoff.std(ddof=1) / math.sqrt(len(disc_payoff)))
    return {"price": price, "stderr": stderr,
            "ci_low": price - 1.96 * stderr, "ci_high": price + 1.96 * stderr,
            "n_paths": int(len(disc_payoff))}


def price_european(S: float, K: float, T: float, r: float, sigma: float,
                   option_type: str = "call", q: float = 0.0,
                   n_paths: int = 200_000, seed: int = 12345,
                   antithetic: bool = True) -> Dict[str, Any]:
    """Vanilla European by terminal-value simulation (no time-stepping needed)."""
    otype = option_type.lower()
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, (S - K) if otype == "call" else (K - S))
        return {"price": intrinsic, "stderr": 0.0, "ci_low": intrinsic,
                "ci_high": intrinsic, "n_paths": 0}
    rng = np.random.default_rng(seed)
    n = n_paths // 2 if antithetic else n_paths
    z = rng.standard_normal(n)
    if antithetic:
        z = np.concatenate([z, -z])
    st = _terminal(S, T, r, sigma, q, z)
    return _summary(math.exp(-r * T) * _payoff(st, K, otype))


def european_convergence(S: float, K: float, T: float, r: float, sigma: float,
                         option_type: str = "call", q: float = 0.0,
                         checkpoints: Sequence[int] = (1000, 5000, 25000, 100000, 400000),
                         seed: int = 12345) -> List[Dict[str, Any]]:
    """Running price and 95% band at increasing path counts, to show convergence."""
    otype = option_type.lower()
    if T <= 0 or sigma <= 0:
        return []
    rng = np.random.default_rng(seed)
    n_max = max(checkpoints)
    st = _terminal(S, T, r, sigma, q, rng.standard_normal(n_max))
    dp = math.exp(-r * T) * _payoff(st, K, otype)
    out = []
    for n in checkpoints:
        sub = dp[:n]
        price = float(sub.mean())
        se = float(sub.std(ddof=1) / math.sqrt(n))
        out.append({"n_paths": int(n), "price": price,
                    "ci_low": price - 1.96 * se, "ci_high": price + 1.96 * se})
    return out


def _paths(S: float, T: float, r: float, sigma: float, q: float, n_paths: int,
           n_steps: int, seed: int, antithetic: bool = True) -> np.ndarray:
    """Simulated GBM paths, shape (paths, n_steps+1), first column S."""
    rng = np.random.default_rng(seed)
    n = n_paths // 2 if antithetic else n_paths
    dt = T / n_steps
    z = rng.standard_normal((n, n_steps))
    if antithetic:
        z = np.concatenate([z, -z], axis=0)
    incr = (r - q - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z
    log_path = np.cumsum(incr, axis=1)
    body = S * np.exp(log_path)
    head = np.full((body.shape[0], 1), float(S))
    return np.concatenate([head, body], axis=1)


def price_asian(S: float, K: float, T: float, r: float, sigma: float,
                option_type: str = "call", q: float = 0.0, average: str = "arithmetic",
                n_paths: int = 100_000, n_steps: int = 50,
                seed: int = 12345) -> Optional[Dict[str, Any]]:
    """Asian option on the average of the monitored path (open excluded)."""
    otype = option_type.lower()
    if T <= 0 or sigma <= 0 or n_steps < 1:
        return None
    paths = _paths(S, T, r, sigma, q, n_paths, n_steps, seed)
    monitored = paths[:, 1:]
    if average == "geometric":
        avg = np.exp(np.log(monitored).mean(axis=1))
    else:
        avg = monitored.mean(axis=1)
    return _summary(math.exp(-r * T) * _payoff(avg, K, otype))


def price_barrier(S: float, K: float, T: float, r: float, sigma: float, barrier: float,
                  barrier_type: str = "up-and-out", option_type: str = "call", q: float = 0.0,
                  n_paths: int = 100_000, n_steps: int = 100,
                  seed: int = 12345) -> Optional[Dict[str, Any]]:
    """
    Barrier option, monitored at each step. barrier_type is one of
    up-and-out, up-and-in, down-and-out, down-and-in.
    """
    otype = option_type.lower()
    bt = barrier_type.lower()
    if T <= 0 or sigma <= 0 or n_steps < 1 or barrier <= 0:
        return None
    paths = _paths(S, T, r, sigma, q, n_paths, n_steps, seed)
    if bt.startswith("up"):
        breached = paths.max(axis=1) >= barrier
    else:
        breached = paths.min(axis=1) <= barrier
    alive = breached if bt.endswith("in") else ~breached
    payoff = _payoff(paths[:, -1], K, otype) * alive
    result = _summary(math.exp(-r * T) * payoff)
    result["knock_probability"] = float(breached.mean())
    return result


def sample_paths(S: float, T: float, r: float, sigma: float, q: float = 0.0,
                 n_paths: int = 200, n_steps: int = 80, seed: int = 7,
                 barrier: Optional[float] = None,
                 barrier_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    A small sample of simulated paths for display, with the time axis in years and,
    when a barrier is given, a per-path flag for whether it was breached. The full
    price uses far more paths; this is just enough to show the cloud.
    """
    if T <= 0 or sigma <= 0 or n_steps < 1:
        return None
    paths = _paths(S, T, r, sigma, q, n_paths, n_steps, seed, antithetic=False)
    times = [round(T * i / n_steps, 5) for i in range(n_steps + 1)]
    breached = None
    if barrier and barrier_type:
        if barrier_type.lower().startswith("up"):
            hit = paths.max(axis=1) >= barrier
        else:
            hit = paths.min(axis=1) <= barrier
        breached = [bool(b) for b in hit]
    return {
        "times": times,
        "paths": [[round(v, 3) for v in row] for row in paths.tolist()],
        "breached": breached,
    }
