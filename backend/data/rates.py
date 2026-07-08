"""
Risk-free rate curve, expiry-matched by interpolation.

Source priority: FRED's dense constant-maturity par curve (1-month to 30-year,
end-of-day, the accurate dense source for rho), then Yahoo's four intraday-ish
points as a fallback, then a flat single rate. The resolved curve is cached for a
few hours because the end-of-day data does not change intraday.
"""
import time
from typing import Callable, Dict, Optional, Tuple

from backend.data import fred, yfinance_client

_CURVE_CACHE = {}
_TTL_SECONDS = 6 * 3600


def interpolate_rate(t_years: float, curve: Dict[float, float]) -> Optional[float]:
    """
    Linearly interpolate the annual rate at t_years from a {tenor: rate} curve.
    Below the shortest tenor returns the shortest rate; above the longest returns
    the longest rate (flat extrapolation at the ends). None if the curve is empty.
    """
    if not curve:
        return None
    tenors = sorted(curve)
    if len(tenors) == 1 or t_years <= tenors[0]:
        return curve[tenors[0]]
    if t_years >= tenors[-1]:
        return curve[tenors[-1]]
    for i in range(1, len(tenors)):
        lo, hi = tenors[i - 1], tenors[i]
        if lo <= t_years <= hi:
            weight = (t_years - lo) / (hi - lo)
            return curve[lo] + weight * (curve[hi] - curve[lo])
    return curve[tenors[-1]]


def build_curve(treasury_rates: Optional[Dict[float, float]],
                fallback_rate: Optional[float] = None) -> Callable[[float], Optional[float]]:
    """
    Return a callable rate(t_years). With a usable curve it interpolates; otherwise
    it falls back to a flat single rate (fallback_rate, or 0.0).
    """
    if treasury_rates:
        return lambda t: interpolate_rate(t, treasury_rates)
    flat = fallback_rate if fallback_rate is not None else 0.0
    return lambda t: flat


def fetch_risk_free_points(use_cache: bool = True) -> Tuple[Optional[Dict[float, float]], Optional[str], Optional[str]]:
    """
    Return (points, source, as_of). FRED is primary (dense, end-of-day), Yahoo the
    fallback (four coarse points), then (None, None, None). Cached for a few hours
    since the curve is end-of-day and does not move intraday.
    """
    if use_cache:
        cached = _CURVE_CACHE.get("data")
        if cached and time.time() - cached[0] < _TTL_SECONDS:
            _, points, source, as_of = cached
            return points, source, as_of

    points, source, as_of = None, None, None
    try:
        points, as_of = fred.get_treasury_curve()
        source = "fred"
    except Exception:
        points = None
    if not points:
        try:
            points = yfinance_client.get_treasury_rates()
            source, as_of = "yahoo", None
        except Exception:
            points = None

    if points:
        _CURVE_CACHE["data"] = (time.time(), points, source, as_of)
        return points, source, as_of
    return None, None, None


def get_rate_curve(fallback_rate: float = 0.04, use_cache: bool = True) -> Tuple[Callable[[float], Optional[float]], str, Dict[float, float], Optional[str]]:
    """
    Return (rate_fn, source, points, as_of). Falls back to a flat rate if no source
    is reachable, so callers always receive a usable function.
    """
    points, source, as_of = fetch_risk_free_points(use_cache=use_cache)
    if points:
        return build_curve(points), source, points, as_of
    return build_curve(None, fallback_rate=fallback_rate), "flat-fallback", {}, None
