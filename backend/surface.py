"""
Volatility-surface analytics: SVI fitted slices, arbitrage detection, and the ATM
term structure. All operate on the normalized chain plus the forward per
expiration. Arbitrage runs on the RAW surface by design, to catch inconsistencies
in the live chain rather than in a smoothed fit.
"""
import math
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pricing_engine import bs_price  # noqa: E402

from backend import svi


def _by_expiration(chain):
    """Group contracts with usable IV by expiration -> {exp: {strike: (iv, T)}}."""
    groups = {}
    for c in chain.contracts:
        if c.iv and c.iv > 0 and c.time_to_expiry and c.time_to_expiry > 0:
            slot = groups.setdefault(c.expiration, {})
            if c.strike not in slot:
                slot[c.strike] = (c.iv, c.time_to_expiry)
    return groups


def _tenor(slot):
    return next(iter(slot.values()))[1]


def _interp(points, x):
    """Linear-interpolate y at x from sorted (x, y) points; None if out of range."""
    if not points or x < points[0][0] or x > points[-1][0]:
        return None
    for i in range(1, len(points)):
        if x <= points[i][0]:
            (x0, y0), (x1, y1) = points[i - 1], points[i]
            t = (x - x0) / ((x1 - x0) or 1.0)
            return y0 + t * (y1 - y0)
    return points[-1][1]


def svi_surface(chain, forwards):
    """
    Fit an SVI slice per expiration. Each slice is either fitted (with a smooth
    curve over its strike range) or marked ok=False, so the overlay hides the
    slices that fail to calibrate rather than showing a distorted fit.
    """
    groups = _by_expiration(chain)
    slices = []
    for exp in sorted(groups, key=lambda e: _tenor(groups[e])):
        strike_iv = sorted(groups[exp].items())
        T = _tenor(groups[exp])
        F = forwards.get(exp)
        if not F or F <= 0:
            continue
        ks = [math.log(K / F) for K, _ in strike_iv]
        ws = [iv * iv * T for _, (iv, _) in strike_iv]
        params = svi.fit_slice(ks, ws)
        entry = {"expiration": exp.isoformat(), "tenor": round(T, 4),
                 "ok": params is not None}
        if params:
            entry["params"] = params
            strikes = [K for K, _ in strike_iv]
            lo, hi = min(strikes), max(strikes)
            curve = []
            for i in range(41):
                K = lo + (hi - lo) * i / 40
                iv = svi.iv_from_params(params, math.log(K / F), T)
                if iv:
                    curve.append({"strike": round(K, 3), "iv": iv})
            entry["curve"] = curve
        slices.append(entry)
    return {"slices": slices}


def arbitrage(chain, forwards, spot, rate_fn, dividend_yield):
    """
    Scan the raw surface for calendar and butterfly arbitrage. Returns a list of
    violations, each with type, location, and a plain-language description.
    """
    groups = _by_expiration(chain)
    q = dividend_yield or 0.0
    butterfly, calendar = [], []

    # Butterfly: call prices must be convex in strike (a non-negative density).
    # We measure the violation as the dollar gap by which the middle call sits above
    # the chord of its neighbours, and flag only material gaps so dense strikes with
    # tick-size quote noise do not swamp genuine dislocations.
    for exp, slot in groups.items():
        strike_iv = sorted(slot.items())
        if len(strike_iv) < 3:
            continue
        T = _tenor(slot)
        r = rate_fn(T)
        prices = [(K, bs_price(spot, K, T, r, iv, "call", q))
                  for K, (iv, _) in strike_iv]
        for i in range(1, len(prices) - 1):
            (k0, c0), (k1, c1), (k2, c2) = prices[i - 1], prices[i], prices[i + 1]
            chord = c0 + (c2 - c0) * (k1 - k0) / ((k2 - k0) or 1.0)
            gap = chord - c1  # >= 0 under no-arbitrage convexity
            tol = max(0.05, 0.02 * c1)
            if gap < -tol:
                butterfly.append({
                    "type": "butterfly", "expiration": exp.isoformat(),
                    "tenor": round(T, 4), "strike": k1, "severity": gap,
                    "description": (
                        f"The {k1:g} call sits ${-gap:.2f} above the no-arbitrage "
                        f"convex bound set by its neighbours, implying a negative "
                        f"risk-neutral density (butterfly arbitrage). Usually a "
                        f"stale or crossed quote at this strike."),
                })

    # Calendar: total variance must not fall with maturity at a fixed moneyness.
    slices = []
    for exp in sorted(groups, key=lambda e: _tenor(groups[e])):
        strike_iv = sorted(groups[exp].items())
        T = _tenor(groups[exp])
        F = forwards.get(exp)
        if not F or F <= 0:
            continue
        kw = [(math.log(K / F), iv * iv * T) for K, (iv, _) in strike_iv]
        slices.append((exp, T, kw))
    for k_level in (-0.10, -0.05, 0.0, 0.05, 0.10):
        prev = None
        for exp, T, kw in slices:
            w = _interp(kw, k_level)
            if w is None:
                continue
            if prev is not None and w < prev[1] * 0.98:
                calendar.append({
                    "type": "calendar", "expiration": exp.isoformat(),
                    "tenor": round(T, 4), "moneyness": k_level,
                    "prior_expiration": prev[0].isoformat(),
                    "description": (
                        f"Total implied variance at {k_level:+.0%} moneyness falls "
                        f"from {prev[0].isoformat()} to {exp.isoformat()} (calendar "
                        f"arbitrage): the shorter-dated option prices more total "
                        f"variance than the longer-dated one."),
                })
            prev = (exp, w)

    butterfly.sort(key=lambda v: v["severity"])  # most negative (worst) first
    reported = calendar + butterfly[:20]
    return {
        "violations": reported,
        "counts": {"butterfly": len(butterfly), "calendar": len(calendar)},
        "truncated": len(butterfly) > 20,
    }


def atm_term_structure(chain, forwards, svi_result):
    """
    ATM implied vol (at the forward) per expiration, from the raw points and, where
    the slice calibrated, from the SVI fit for a smoother curve.
    """
    groups = _by_expiration(chain)
    svi_by_exp = {s["expiration"]: s for s in svi_result.get("slices", [])}
    points = []
    for exp in sorted(groups, key=lambda e: _tenor(groups[e])):
        strike_iv = sorted(groups[exp].items())
        T = _tenor(groups[exp])
        F = forwards.get(exp)
        if not F or F <= 0:
            continue
        raw = _interp([(K, iv) for K, (iv, _) in strike_iv], F)
        pt = {"expiration": exp.isoformat(), "tenor": round(T, 4), "atm_raw": raw}
        sl = svi_by_exp.get(exp.isoformat())
        if sl and sl.get("ok") and sl.get("params"):
            pt["atm_svi"] = svi.iv_from_params(sl["params"], 0.0, T)
        points.append(pt)
    return {"points": points}
