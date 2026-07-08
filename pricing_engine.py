"""
Options pricing engine.
Black-Scholes-Merton pricing, analytical Greeks, binomial (CRR) American pricing,
implied volatility solver, realized volatility, probability of profit, breakeven.

The closed-form price, Greeks, and implied-vol solver accept either scalars or NumPy
arrays. Scalar inputs run the pure-Python reference computation and return a float;
array inputs run a vectorized NumPy computation and return an array, so an entire
chain prices in one call. The two paths agree to floating-point precision, checked
in verify_engine_vec.

Conventions:
  S  = underlying spot price
  K  = strike price
  T  = time to expiry in years
  r  = risk-free rate (annualized, continuous)
  q  = continuous dividend yield (annualized)
  sigma = volatility (annualized)
  option_type = 'call' or 'put'
"""
from __future__ import annotations

import math
from math import erf, exp, log, sqrt
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from scipy.special import erf as _erf

Number = Union[float, np.ndarray]
OptionType = Union[str, Sequence[str]]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * math.pi)


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float,
           q: float = 0.0) -> Tuple[Optional[float], Optional[float]]:
    if T <= 0 or sigma <= 0:
        return None, None
    d1 = (log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    return d1, d2


def _scalar_inputs(*args: Number) -> bool:
    return all(np.ndim(a) == 0 for a in args)


def _cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf(x / np.sqrt(2.0)))


def _pdf(x: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi)


def _call_mask(option_type: OptionType, shape: Tuple[int, ...]) -> np.ndarray:
    if isinstance(option_type, str):
        return np.full(shape, option_type.lower() == "call")
    flags = np.array([str(o).lower() == "call" for o in np.ravel(option_type)], dtype=bool)
    return np.broadcast_to(flags.reshape(np.shape(option_type)), shape)


def _broadcast(S: Number, K: Number, T: Number, r: Number, sigma: Number,
               q: Number) -> List[np.ndarray]:
    return np.broadcast_arrays(*[np.asarray(v, dtype=float) for v in (S, K, T, r, sigma, q)])


def _bs_price_arr(S, K, T, r, sigma, option_type, q):
    S, K, T, r, sigma, q = _broadcast(S, K, T, r, sigma, q)
    is_call = _call_mask(option_type, S.shape)
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
    disc_intr = np.where(is_call,
                         np.maximum(S * disc_q - K * disc_r, 0.0),
                         np.maximum(K * disc_r - S * disc_q, 0.0))
    price = np.where(sigma > 0, price, disc_intr)
    intr = np.where(is_call, np.maximum(S - K, 0.0), np.maximum(K - S, 0.0))
    return np.where(T > 0, price, intr)


def _bs_greeks_arr(S, K, T, r, sigma, option_type, q):
    S, K, T, r, sigma, q = _broadcast(S, K, T, r, sigma, q)
    is_call = _call_mask(option_type, S.shape)
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
    return {"delta": np.where(valid, delta, nan), "gamma": np.where(valid, gamma, nan),
            "vega": np.where(valid, vega, nan), "theta": np.where(valid, theta, nan),
            "rho": np.where(valid, rho, nan)}


def _implied_vol_arr(market_price, S, K, T, r, option_type, q, tol, max_iter):
    price, S, K, T, r, q = np.broadcast_arrays(
        *[np.asarray(v, dtype=float) for v in (market_price, S, K, T, r, q)])
    is_call = _call_mask(option_type, price.shape)
    disc_q = np.exp(-q * np.where(T > 0, T, 1.0))
    disc_r = np.exp(-r * np.where(T > 0, T, 1.0))
    intrinsic = np.where(is_call, np.maximum(S * disc_q - K * disc_r, 0.0),
                         np.maximum(K * disc_r - S * disc_q, 0.0))
    lo = np.full(price.shape, 1e-6)
    hi = np.full(price.shape, 5.0)
    price_lo = _bs_price_arr(S, K, T, r, lo, option_type, q)
    price_hi = _bs_price_arr(S, K, T, r, hi, option_type, q)
    solvable = (T > 0) & (market_price > 0) & (price >= intrinsic - tol) \
        & ((price_lo - price) * (price_hi - price) <= 0)
    plo = price_lo.copy()
    mid = 0.5 * (lo + hi)
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        pmid = _bs_price_arr(S, K, T, r, mid, option_type, q)
        conv = np.abs(pmid - price) < tol
        go_hi = (plo - price) * (pmid - price) < 0
        move = ~conv
        hi = np.where(move & go_hi, mid, hi)
        lo_new = np.where(move & ~go_hi, mid, lo)
        plo = np.where(move & ~go_hi, pmid, plo)
        lo = lo_new
        if conv[solvable].all() if solvable.any() else True:
            break
    return np.where(solvable, 0.5 * (lo + hi), np.nan)


def bs_price(S: Number, K: Number, T: Number, r: Number, sigma: Number,
             option_type: OptionType, q: Number = 0.0) -> Number:
    """Black-Scholes-Merton price for a European option with continuous dividend yield."""
    if not _scalar_inputs(S, K, T, r, sigma, q):
        return _bs_price_arr(S, K, T, r, sigma, option_type, q)
    if T <= 0:
        if option_type == 'call':
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        fwd = S * exp(-q * T)
        disc_k = K * exp(-r * T)
        if option_type == 'call':
            return max(fwd - disc_k, 0.0)
        return max(disc_k - fwd, 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    if option_type == 'call':
        return S * exp(-q * T) * _norm_cdf(d1) - K * exp(-r * T) * _norm_cdf(d2)
    elif option_type == 'put':
        return K * exp(-r * T) * _norm_cdf(-d2) - S * exp(-q * T) * _norm_cdf(-d1)
    raise ValueError("option_type must be 'call' or 'put'")


def bs_greeks(S: Number, K: Number, T: Number, r: Number, sigma: Number,
              option_type: OptionType, q: Number = 0.0) -> Dict[str, Number]:
    """
    The five primary Greeks.
      delta : d(price)/d(spot)
      gamma : d(delta)/d(spot)
      vega  : d(price)/d(vol), per 1.00 change in sigma (divide by 100 for per-1%-point)
      theta : d(price)/d(time), per year (divide by 365 for per-calendar-day)
      rho   : d(price)/d(rate), per 1.00 change in r (divide by 100 for per-1%-point)
    """
    if not _scalar_inputs(S, K, T, r, sigma, q):
        return _bs_greeks_arr(S, K, T, r, sigma, option_type, q)
    if T <= 0 or sigma <= 0:
        return {'delta': float('nan'), 'gamma': float('nan'),
                'vega': float('nan'), 'theta': float('nan'), 'rho': float('nan')}

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    pdf_d1 = _norm_pdf(d1)
    sqrtT = sqrt(T)

    gamma = exp(-q * T) * pdf_d1 / (S * sigma * sqrtT)
    vega = S * exp(-q * T) * pdf_d1 * sqrtT

    if option_type == 'call':
        delta = exp(-q * T) * _norm_cdf(d1)
        theta = (-(S * exp(-q * T) * pdf_d1 * sigma) / (2.0 * sqrtT)
                 - r * K * exp(-r * T) * _norm_cdf(d2)
                 + q * S * exp(-q * T) * _norm_cdf(d1))
        rho = K * T * exp(-r * T) * _norm_cdf(d2)
    elif option_type == 'put':
        delta = -exp(-q * T) * _norm_cdf(-d1)
        theta = (-(S * exp(-q * T) * pdf_d1 * sigma) / (2.0 * sqrtT)
                 + r * K * exp(-r * T) * _norm_cdf(-d2)
                 - q * S * exp(-q * T) * _norm_cdf(-d1))
        rho = -K * T * exp(-r * T) * _norm_cdf(-d2)
    else:
        raise ValueError("option_type must be 'call' or 'put'")

    return {'delta': delta, 'gamma': gamma, 'vega': vega, 'theta': theta, 'rho': rho}


def binomial_price(S: float, K: float, T: float, r: float, sigma: float,
                   option_type: str, q: float = 0.0, steps: int = 200,
                   american: bool = True) -> float:
    """
    Cox-Ross-Rubinstein binomial tree.
    Handles American early exercise, which Black-Scholes cannot. For European inputs
    with enough steps it converges to the Black-Scholes price.
    """
    if T <= 0:
        if option_type == 'call':
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        return bs_price(S, K, T, r, sigma, option_type, q)

    dt = T / steps
    u = exp(sigma * sqrt(dt))
    d = 1.0 / u
    disc = exp(-r * dt)
    p = (exp((r - q) * dt) - d) / (u - d)
    if p < 0 or p > 1:
        return bs_price(S, K, T, r, sigma, option_type, q)

    values = []
    for i in range(steps + 1):
        ST = S * (u ** (steps - i)) * (d ** i)
        if option_type == 'call':
            values.append(max(ST - K, 0.0))
        else:
            values.append(max(K - ST, 0.0))

    for step in range(steps - 1, -1, -1):
        for i in range(step + 1):
            cont = disc * (p * values[i] + (1.0 - p) * values[i + 1])
            if american:
                ST = S * (u ** (step - i)) * (d ** i)
                if option_type == 'call':
                    exercise = max(ST - K, 0.0)
                else:
                    exercise = max(K - ST, 0.0)
                values[i] = max(cont, exercise)
            else:
                values[i] = cont
    return values[0]


def implied_vol(market_price: Number, S: Number, K: Number, T: Number, r: Number,
                option_type: OptionType, q: Number = 0.0,
                tol: float = 1e-6, max_iter: int = 100) -> Union[Optional[float], np.ndarray]:
    """
    Volatility that reproduces the observed market price under Black-Scholes.
    Bisection is used rather than Newton because it cannot diverge on the flat,
    near-zero-vega wings where a market price barely moves with vol.
    Returns None (scalar) or NaN (array) where no solution exists in range, e.g. a
    price below intrinsic.
    """
    if not _scalar_inputs(market_price, S, K, T, r, q):
        return _implied_vol_arr(market_price, S, K, T, r, option_type, q, tol, max_iter)
    if T <= 0 or market_price <= 0:
        return None

    if option_type == 'call':
        intrinsic = max(S * exp(-q * T) - K * exp(-r * T), 0.0)
    else:
        intrinsic = max(K * exp(-r * T) - S * exp(-q * T), 0.0)
    if market_price < intrinsic - tol:
        return None

    lo, hi = 1e-6, 5.0
    price_lo = bs_price(S, K, T, r, lo, option_type, q)
    price_hi = bs_price(S, K, T, r, hi, option_type, q)
    if (price_lo - market_price) * (price_hi - market_price) > 0:
        return None

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        price_mid = bs_price(S, K, T, r, mid, option_type, q)
        if abs(price_mid - market_price) < tol:
            return mid
        if (price_lo - market_price) * (price_mid - market_price) < 0:
            hi = mid
        else:
            lo = mid
            price_lo = price_mid
    return 0.5 * (lo + hi)


def realized_vol(closes: Sequence[float], window: Optional[int] = None,
                 annualization: int = 252) -> Optional[float]:
    """
    Annualized close-to-close realized volatility from a series of closing prices,
    oldest first. With `window`, only the most recent `window` returns are used.
    Returns a decimal (0.20 = 20%).
    """
    if len(closes) < 2:
        return None
    log_returns = [log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    if window is not None:
        log_returns = log_returns[-window:]
    n = len(log_returns)
    if n < 2:
        return None
    mean = sum(log_returns) / n
    variance = sum((x - mean) ** 2 for x in log_returns) / (n - 1)
    return sqrt(variance) * sqrt(annualization)


def garman_klass_vol(opens: Sequence[float], highs: Sequence[float],
                     lows: Sequence[float], closes: Sequence[float],
                     window: Optional[int] = None,
                     annualization: int = 252) -> Optional[float]:
    """
    Garman-Klass realized volatility from OHLC bars, per-session variance
        0.5 * ln(H/L)^2  -  (2*ln2 - 1) * ln(C/O)^2
    annualized as sqrt(annualization * mean_session_variance).

    It assumes continuous trading with no jumps, so it understates vol when the
    underlying gaps between sessions: an overnight gap moves close-to-close but not
    the intraday range, so for frequently gapping names it can sit below the
    close-to-close figure for that structural reason.

    Returns a decimal (0.20 = 20%), or None with no data.
    """
    n = min(len(opens), len(highs), len(lows), len(closes))
    k = 2.0 * log(2.0) - 1.0
    daily = []
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            continue
        hl = log(h / l)
        co = log(c / o)
        daily.append(0.5 * hl * hl - k * co * co)
    if window is not None:
        daily = daily[-window:]
    if not daily:
        return None
    mean_var = sum(daily) / len(daily)
    if mean_var <= 0:
        return 0.0
    return sqrt(mean_var * annualization)


def prob_itm(S: float, K: float, T: float, r: float, sigma: float,
             option_type: str, q: float = 0.0) -> Optional[float]:
    """
    Risk-neutral probability of finishing in the money at expiry under the lognormal
    model, N(d2) for a call and N(-d2) for a put. Risk-neutral, not real-world.
    """
    if T <= 0 or sigma <= 0:
        return None
    _, d2 = _d1_d2(S, K, T, r, sigma, q)
    if option_type == 'call':
        return _norm_cdf(d2)
    return _norm_cdf(-d2)


def prob_profit_long_option(S: float, K: float, T: float, r: float, sigma: float,
                            option_type: str, premium: float,
                            q: float = 0.0) -> Optional[float]:
    """
    Risk-neutral probability of finishing beyond the breakeven for a single long
    option, where breakeven is K + premium for a call and K - premium for a put.
    """
    if T <= 0 or sigma <= 0:
        return None
    if option_type == 'call':
        breakeven = K + premium
    else:
        breakeven = K - premium
        if breakeven <= 0:
            return 1.0
    _, d2_be = _d1_d2(S, breakeven, T, r, sigma, q)
    if option_type == 'call':
        return _norm_cdf(d2_be)
    return _norm_cdf(-d2_be)


def breakeven_long_option(K: float, premium: float, option_type: str) -> float:
    """Breakeven underlying price at expiry for a single long option."""
    if option_type == 'call':
        return K + premium
    return K - premium
