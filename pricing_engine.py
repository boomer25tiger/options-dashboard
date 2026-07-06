"""
Options pricing engine.
Black-Scholes-Merton pricing, analytical Greeks, binomial (CRR) American pricing,
implied volatility solver, realized volatility, probability of profit, breakeven.

All functions are pure and depend on no external data, so their correctness can be
verified against published reference values.

Conventions:
  S  = underlying spot price
  K  = strike price
  T  = time to expiry in years
  r  = risk-free rate (annualized, continuous)
  q  = continuous dividend yield (annualized)
  sigma = volatility (annualized)
  option_type = 'call' or 'put'
"""

import math
from math import log, sqrt, exp, erf


# ---------------------------------------------------------------------------
# Normal distribution helpers (no scipy dependency for portability)
# ---------------------------------------------------------------------------

def _norm_cdf(x):
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x):
    """Standard normal probability density function."""
    return exp(-0.5 * x * x) / sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# Black-Scholes-Merton pricing
# ---------------------------------------------------------------------------

def _d1_d2(S, K, T, r, sigma, q=0.0):
    if T <= 0 or sigma <= 0:
        return None, None
    d1 = (log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    return d1, d2


def bs_price(S, K, T, r, sigma, option_type, q=0.0):
    """Black-Scholes-Merton price for a European option with continuous dividend yield."""
    if T <= 0:
        # At expiry the option is worth its intrinsic value.
        if option_type == 'call':
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        # Zero volatility collapses to discounted intrinsic value.
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


# ---------------------------------------------------------------------------
# Analytical Greeks
# ---------------------------------------------------------------------------

def bs_greeks(S, K, T, r, sigma, option_type, q=0.0):
    """
    Returns a dict of the five primary Greeks.
      delta : d(price)/d(spot)
      gamma : d(delta)/d(spot)
      vega  : d(price)/d(vol), per 1.00 change in sigma (divide by 100 for per-1%-point)
      theta : d(price)/d(time), per year (divide by 365 for per-calendar-day)
      rho   : d(price)/d(rate), per 1.00 change in r (divide by 100 for per-1%-point)
    """
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


# ---------------------------------------------------------------------------
# Binomial (Cox-Ross-Rubinstein) pricing with American early exercise
# ---------------------------------------------------------------------------

def binomial_price(S, K, T, r, sigma, option_type, q=0.0, steps=200, american=True):
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
    # Risk-neutral up-probability with dividend yield.
    p = (exp((r - q) * dt) - d) / (u - d)
    if p < 0 or p > 1:
        # Numerical guard: fall back to Black-Scholes if params make p invalid.
        return bs_price(S, K, T, r, sigma, option_type, q)

    # Terminal asset prices and payoffs.
    values = []
    for i in range(steps + 1):
        ST = S * (u ** (steps - i)) * (d ** i)
        if option_type == 'call':
            values.append(max(ST - K, 0.0))
        else:
            values.append(max(K - ST, 0.0))

    # Backward induction.
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


# ---------------------------------------------------------------------------
# Implied volatility solver
# ---------------------------------------------------------------------------

def implied_vol(market_price, S, K, T, r, option_type, q=0.0,
                tol=1e-6, max_iter=100):
    """
    Solve for the volatility that reproduces the observed market price under
    Black-Scholes. Uses bisection for robustness, which cannot diverge the way
    Newton's method can on badly-behaved inputs.
    Returns None if no solution exists in a sensible range (e.g. price below intrinsic).
    """
    if T <= 0 or market_price <= 0:
        return None

    # Intrinsic value floor; a price below intrinsic has no valid IV.
    if option_type == 'call':
        intrinsic = max(S * exp(-q * T) - K * exp(-r * T), 0.0)
    else:
        intrinsic = max(K * exp(-r * T) - S * exp(-q * T), 0.0)
    if market_price < intrinsic - tol:
        return None

    lo, hi = 1e-6, 5.0  # vol search range: 0% to 500%
    price_lo = bs_price(S, K, T, r, lo, option_type, q)
    price_hi = bs_price(S, K, T, r, hi, option_type, q)
    if (price_lo - market_price) * (price_hi - market_price) > 0:
        # Price not bracketed within the search range.
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


# ---------------------------------------------------------------------------
# Realized (historical) volatility
# ---------------------------------------------------------------------------

def realized_vol(closes, window=None, annualization=252):
    """
    Annualized realized volatility from a series of closing prices using
    close-to-close log returns.
      closes : list of closing prices, oldest first
      window : if given, use only the most recent `window` returns
    Returns annualized volatility as a decimal (0.20 = 20%).
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


def garman_klass_vol(opens, highs, lows, closes, window=None, annualization=252):
    """
    Garman-Klass realized volatility from OHLC bars.

    Uses each session's high-low range and open-close move, which makes it more
    efficient (lower variance) than close-to-close, especially at short windows.
    Per-session variance estimate:
        0.5 * ln(H/L)^2  -  (2*ln2 - 1) * ln(C/O)^2
    Annualized as sqrt(annualization * mean_session_variance).

    CAVEAT: it assumes continuous trading with no jumps, so it UNDERSTATES vol when
    the underlying gaps between sessions (an overnight gap moves close-to-close but
    not the intraday range). For frequently gapping names it can sit below the
    close-to-close figure for that structural reason.

    Returns annualized volatility as a decimal (0.20 = 20%), or None with no data.
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


# ---------------------------------------------------------------------------
# Probability of profit and breakeven
# ---------------------------------------------------------------------------

def prob_itm(S, K, T, r, sigma, option_type, q=0.0):
    """
    Risk-neutral probability that the option finishes in the money at expiry
    under the lognormal (Black-Scholes) model. This equals N(d2) for a call and
    N(-d2) for a put. It is the risk-neutral probability, not a real-world one.
    """
    if T <= 0 or sigma <= 0:
        return None
    _, d2 = _d1_d2(S, K, T, r, sigma, q)
    if option_type == 'call':
        return _norm_cdf(d2)
    return _norm_cdf(-d2)


def prob_profit_long_option(S, K, T, r, sigma, option_type, premium, q=0.0):
    """
    Probability the underlying finishes beyond the breakeven for a single long option.
    Breakeven for a long call is K + premium; for a long put, K - premium.
    Computed as the risk-neutral probability of finishing beyond that breakeven price.
    """
    if T <= 0 or sigma <= 0:
        return None
    if option_type == 'call':
        breakeven = K + premium
    else:
        breakeven = K - premium
        if breakeven <= 0:
            return 1.0
    # Probability S_T > breakeven (call) or S_T < breakeven (put) under lognormal.
    _, d2_be = _d1_d2(S, breakeven, T, r, sigma, q)
    if option_type == 'call':
        return _norm_cdf(d2_be)
    return _norm_cdf(-d2_be)


def breakeven_long_option(K, premium, option_type):
    """Breakeven underlying price at expiry for a single long option."""
    if option_type == 'call':
        return K + premium
    return K - premium
