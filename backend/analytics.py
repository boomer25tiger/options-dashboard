"""
Analytics derived from stock bars and the normalized chain.

Realized-vol windows, the realized-vol RANK proxy (the day-one stand-in for IV
rank / percentile per CLAUDE.md feature 6, until the stored history accumulates a
real IV series), the at-the-money implied vol, and point extraction for the
volatility surface and smile.
"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pricing_engine import realized_vol  # noqa: E402


def realized_vol_windows(closes, windows=(10, 20, 30, 60)):
    """Annualized realized vol for each lookback window."""
    return {w: realized_vol(closes, window=w) for w in windows}


def realized_vol_series(closes, window=20):
    """Rolling annualized realized vol, one value per day once enough history exists."""
    need = window + 1
    series = []
    for end in range(need, len(closes) + 1):
        rv = realized_vol(closes[end - need:end], window=window)
        if rv is not None:
            series.append(rv)
    return series


def realized_vol_rank(closes, window=20, lookback=252):
    """
    Realized-vol rank proxy. 'rank' is the current value's position within the
    [min, max] band of the lookback window (IV-rank style, 0-100). 'percentile' is
    the share of days at or below the current value (IV-percentile style, 0-100).
    """
    series = realized_vol_series(closes, window=window)
    if len(series) < 2:
        return None
    dist = series[-lookback:] if len(series) > lookback else series
    current = dist[-1]
    lo, hi = min(dist), max(dist)
    rank = 0.0 if hi == lo else (current - lo) / (hi - lo) * 100.0
    below = sum(1 for v in dist if v <= current)
    percentile = below / len(dist) * 100.0
    return {
        "value": current, "min": lo, "max": hi,
        "rank": rank, "percentile": percentile,
        "window": window, "lookback": len(dist), "proxy": "realized_vol",
    }


def atm_iv(chain, expiration=None):
    """IV of the contract nearest the money, optionally within one expiration."""
    if not chain.spot:
        return None
    cands = [c for c in chain.contracts
             if c.iv and (expiration is None or c.expiration == expiration)]
    if not cands:
        return None
    return min(cands, key=lambda c: abs(c.strike - chain.spot)).iv


def surface_points(chain):
    """
    One IV per (expiration, strike) for the 3D surface, preferring the out-of-the-
    money side (put below spot, call above), which carries the cleaner vol quote.
    """
    spot = chain.spot
    best = {}
    for c in chain.contracts:
        if not (c.iv and c.time_to_expiry and c.time_to_expiry > 0):
            continue
        key = (c.expiration, c.strike)
        otm = True
        if spot:
            otm = ((c.option_type == "put" and c.strike <= spot)
                   or (c.option_type == "call" and c.strike >= spot))
        current = best.get(key)
        if current is None or (otm and not current[1]):
            best[key] = (c, otm)
    points = [
        {"strike": c.strike, "expiration": c.expiration.isoformat(),
         "tenor": round(c.time_to_expiry, 4), "iv": c.iv}
        for c, _ in best.values()
    ]
    points.sort(key=lambda p: (p["expiration"], p["strike"]))
    return points


def smile_points(chain, expiration):
    """IV vs strike for one expiration (a 2D slice of the surface)."""
    points = [
        {"strike": c.strike, "iv": c.iv, "type": c.option_type,
         "in_the_money": c.in_the_money}
        for c in chain.contracts if c.iv and c.expiration == expiration
    ]
    points.sort(key=lambda p: (p["type"], p["strike"]))
    return points
