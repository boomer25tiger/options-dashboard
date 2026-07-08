"""
Vectorized pricing engine.

NumPy port of the Black-Scholes price, Greeks, and implied-vol solver from
pricing_engine.py, so an entire options chain prices in one array operation instead
of a Python loop over strikes. The scalar engine stays the reference and one source
of truth for the math; this reproduces it element for element (verified in
verify_engine_vec.py) and exists for speed on chain-wide work.

Every function broadcasts its scalar/array inputs. option_type is either a single
'call'/'put' applied to all, or an array of them, one per contract.
"""
import numpy as np
from scipy.special import erf


def _cdf(x):
    return 0.5 * (1.0 + erf(x / np.sqrt(2.0)))


def _pdf(x):
    return np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi)


def _is_call(option_type, shape):
    if isinstance(option_type, str):
        return np.full(shape, option_type.lower() == "call")
    flags = np.array([str(o).lower() == "call" for o in np.ravel(option_type)], dtype=bool)
    return np.broadcast_to(flags.reshape(np.shape(option_type)), shape)


def _broadcast(S, K, T, r, sigma, q):
    arrs = np.broadcast_arrays(*[np.asarray(v, dtype=float) for v in (S, K, T, r, sigma, q)])
    return arrs


def bs_price_vec(S, K, T, r, sigma, option_type="call", q=0.0):
    """Black-Scholes-Merton price, vectorized. Matches pricing_engine.bs_price."""
    S, K, T, r, sigma, q = _broadcast(S, K, T, r, sigma, q)
    is_call = _is_call(option_type, S.shape)

    t_safe = np.where(T > 0, T, 1.0)
    sig_safe = np.where(sigma > 0, sigma, 1.0)
    sqrt_t = np.sqrt(t_safe)
    d1 = (np.log(S / K) + (r - q + 0.5 * sig_safe * sig_safe) * t_safe) / (sig_safe * sqrt_t)
    d2 = d1 - sig_safe * sqrt_t
    disc_q = np.exp(-q * t_safe)
    disc_r = np.exp(-r * t_safe)
    call = S * disc_q * _cdf(d1) - K * disc_r * _cdf(d2)
    put = K * disc_r * _cdf(-d2) - S * disc_q * _cdf(-d1)
    price = np.where(is_call, call, put)

    # sigma <= 0 collapses to discounted intrinsic; T <= 0 to plain intrinsic.
    disc_intr = np.where(is_call,
                         np.maximum(S * disc_q - K * disc_r, 0.0),
                         np.maximum(K * disc_r - S * disc_q, 0.0))
    price = np.where(sigma > 0, price, disc_intr)
    intr = np.where(is_call, np.maximum(S - K, 0.0), np.maximum(K - S, 0.0))
    price = np.where(T > 0, price, intr)
    return price


def bs_greeks_vec(S, K, T, r, sigma, option_type="call", q=0.0):
    """
    Analytical Greeks, vectorized, in the same units as pricing_engine.bs_greeks
    (vega per 1.00 vol, theta per year, rho per 1.00 rate). Returns a dict of arrays,
    NaN where T <= 0 or sigma <= 0, matching the scalar engine.
    """
    S, K, T, r, sigma, q = _broadcast(S, K, T, r, sigma, q)
    is_call = _is_call(option_type, S.shape)
    valid = (T > 0) & (sigma > 0)

    t_safe = np.where(valid, T, 1.0)
    sig_safe = np.where(valid, sigma, 1.0)
    sqrt_t = np.sqrt(t_safe)
    d1 = (np.log(S / K) + (r - q + 0.5 * sig_safe * sig_safe) * t_safe) / (sig_safe * sqrt_t)
    d2 = d1 - sig_safe * sqrt_t
    pdf_d1 = _pdf(d1)
    disc_q = np.exp(-q * t_safe)
    disc_r = np.exp(-r * t_safe)

    gamma = disc_q * pdf_d1 / (S * sig_safe * sqrt_t)
    vega = S * disc_q * pdf_d1 * sqrt_t
    delta = np.where(is_call, disc_q * _cdf(d1), -disc_q * _cdf(-d1))
    common_theta = -(S * disc_q * pdf_d1 * sig_safe) / (2.0 * sqrt_t)
    call_theta = common_theta - r * K * disc_r * _cdf(d2) + q * S * disc_q * _cdf(d1)
    put_theta = common_theta + r * K * disc_r * _cdf(-d2) - q * S * disc_q * _cdf(-d1)
    theta = np.where(is_call, call_theta, put_theta)
    rho = np.where(is_call, K * t_safe * disc_r * _cdf(d2), -K * t_safe * disc_r * _cdf(-d2))

    nan = np.full(S.shape, np.nan)
    return {
        "delta": np.where(valid, delta, nan),
        "gamma": np.where(valid, gamma, nan),
        "vega": np.where(valid, vega, nan),
        "theta": np.where(valid, theta, nan),
        "rho": np.where(valid, rho, nan),
    }


def implied_vol_vec(market_price, S, K, T, r, option_type="call", q=0.0,
                    tol=1e-6, max_iter=100):
    """
    Vectorized bisection implied vol over the same 0-500% range as the scalar
    solver. Returns an array with NaN where no solution exists (price below
    intrinsic or not bracketed), the array analogue of the scalar's None.
    """
    price, S, K, T, r, q = np.broadcast_arrays(
        *[np.asarray(v, dtype=float) for v in (market_price, S, K, T, r, q)])
    is_call = _is_call(option_type, price.shape)

    disc_q = np.exp(-q * np.where(T > 0, T, 1.0))
    disc_r = np.exp(-r * np.where(T > 0, T, 1.0))
    intrinsic = np.where(is_call, np.maximum(S * disc_q - K * disc_r, 0.0),
                         np.maximum(K * disc_r - S * disc_q, 0.0))

    lo = np.full(price.shape, 1e-6)
    hi = np.full(price.shape, 5.0)
    price_lo = bs_price_vec(S, K, T, r, lo, option_type, q)
    price_hi = bs_price_vec(S, K, T, r, hi, option_type, q)
    solvable = (T > 0) & (market_price > 0) & (price >= intrinsic - tol) \
        & ((price_lo - price) * (price_hi - price) <= 0)

    plo = price_lo.copy()
    mid = 0.5 * (lo + hi)
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        pmid = bs_price_vec(S, K, T, r, mid, option_type, q)
        conv = np.abs(pmid - price) < tol
        go_hi = (plo - price) * (pmid - price) < 0
        # Freeze brackets on converged entries; otherwise move the right side.
        move = ~conv
        hi = np.where(move & go_hi, mid, hi)
        lo_new = np.where(move & ~go_hi, mid, lo)
        plo = np.where(move & ~go_hi, pmid, plo)
        lo = lo_new
        if conv[solvable].all() if solvable.any() else True:
            break

    result = 0.5 * (lo + hi)
    return np.where(solvable, result, np.nan)
