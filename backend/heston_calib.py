"""
Heston calibration to the live options chain.

Recovers the five Heston parameters by minimising pricing error across strikes and
maturities with scipy least_squares. Fits on relative price residuals for speed
(cheap, and it down-weights expensive in-the-money options the way vega weighting
would), then reports fit quality in implied-vol points, which is the interpretable
number for the UI.

Targets are Black-Scholes prices at each contract's own implied vol, so the fit is
to the market's IV surface. Calibration is non-convex, so the variances seed from
ATM implied and the correlation seeds negative for equity skew. Degrades gracefully:
returns ok=False (never a bad fit dressed up as good) when scipy is absent, too few
instruments survive, the solve throws, or the IV fit is too loose.
"""
import math
import os
import statistics
import sys
from datetime import date
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from backend.data.models import OptionChain

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from heston import feller_ok, heston_price  # noqa: E402
from pricing_engine import bs_price, implied_vol  # noqa: E402

try:
    from scipy.optimize import least_squares
    _HAVE_SCIPY = True
except ImportError:  # scipy is optional; the surface/pricer still work without it
    _HAVE_SCIPY = False

MIN_INSTRUMENTS = 8
_GL_CALIB = 64            # lighter quadrature inside the optimiser
_GL_REPORT = 128          # full quadrature for the reported fit
_IV_RMSE_OK = 0.03        # 3 vol points; looser than this is flagged as a poor fit

# Sample strikes spread across the wing-to-wing band so the fit sees the skew,
# rather than clustering near the money where correlation is barely identified.
_MONEYNESS_TARGETS = (0.88, 0.92, 0.96, 1.00, 1.04, 1.08, 1.12)

_LO = [1e-4, 1e-2, 1e-4, 1e-2, -0.999]   # v0, kappa, theta, xi, rho
_HI = [0.36, 20.0, 0.36, 3.0, 0.5]       # variances capped at 60% vol, sane for equities

# Calibration needs a spread of maturities to identify the long-run variance and
# mean reversion. Near-dated expiries alone (SPY lists them almost daily) leave
# theta unconstrained, so pick expirations nearest these day targets across the curve.
_TENOR_TARGETS_DAYS = (14, 30, 60, 90, 150, 240, 365)


def select_expirations(all_dates: Sequence[date], today: date, max_exps: int = 7) -> List[date]:
    """Pick a maturity-diverse subset of expirations nearest the tenor targets."""
    usable = [d for d in all_dates if (d - today).days >= 5]
    if not usable:
        return []
    chosen = {}
    for target in _TENOR_TARGETS_DAYS:
        best = min(usable, key=lambda d: abs((d - today).days - target))
        chosen[best] = None
    return sorted(chosen)[:max_exps]


def _select_instruments(chain: "OptionChain", spot: float,
                        rate_fn: Callable[[float], float], q: float) -> List[Dict[str, Any]]:
    """Out-of-the-money options sampled across the wing-to-wing band, per slice.

    For each expiration and each moneyness target, take the nearest strike of the
    out-of-the-money type (puts below the money, calls above). Spanning the band is
    what lets the fit identify the skew.
    """
    if not spot:
        return []
    by_exp = {}
    for c in chain.contracts:
        if not (c.iv and 0.02 <= c.iv <= 1.5):
            continue
        if not (c.time_to_expiry and c.time_to_expiry >= 0.02):  # skip ~< 5 trading days
            continue
        moneyness = c.strike / spot
        if moneyness < 0.83 or moneyness > 1.17:
            continue
        by_exp.setdefault(c.expiration, []).append(c)

    instruments = []
    for exp, cs in by_exp.items():
        chosen = {}
        for target in _MONEYNESS_TARGETS:
            otype = "put" if target < 1.0 else "call"
            cands = [c for c in cs if c.option_type == otype]
            if not cands:
                continue
            best = min(cands, key=lambda c: abs(c.strike / spot - target))
            chosen[best.strike] = best  # dedup when targets map to the same strike
        for c in chosen.values():
            T = c.time_to_expiry
            r = rate_fn(T)
            target_price = bs_price(spot, c.strike, T, r, c.iv, c.option_type, q)
            if target_price is None or target_price <= 0.01:
                continue
            instruments.append({
                "K": c.strike, "T": T, "r": r, "q": q, "otype": c.option_type,
                "price": target_price, "iv": c.iv, "expiration": exp,
            })
    return instruments


def _seed(instruments: List[Dict[str, Any]]) -> List[float]:
    """Initial parameter guess from the instruments' own implied vols."""
    ivs = [ins["iv"] for ins in instruments]
    near = min(instruments, key=lambda ins: (ins["T"], abs(math.log(ins["K"]))))
    v0 = near["iv"] ** 2
    theta = statistics.median(ivs) ** 2
    x0 = [v0, 2.0, theta, 0.5, -0.6]
    return [min(max(v, _LO[i]), _HI[i]) for i, v in enumerate(x0)]


def _iv_errors(instruments: List[Dict[str, Any]], params: Sequence[float],
               spot: float) -> List[Tuple[date, float, float]]:
    """Per-instrument (expiration, tenor, Heston-IV minus market-IV)."""
    v0, kappa, theta, xi, rho = params
    errs = []
    for ins in instruments:
        price = heston_price(spot, ins["K"], ins["T"], ins["r"], v0, kappa, theta,
                             xi, rho, ins["otype"], ins["q"], gl_n=_GL_REPORT)
        hiv = implied_vol(price, spot, ins["K"], ins["T"], ins["r"], ins["otype"], ins["q"])
        if hiv is not None:
            errs.append((ins["expiration"], ins["T"], hiv - ins["iv"]))
    return errs


def _rmse(values: Sequence[float]) -> Optional[float]:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else None


def calibrate_instruments(instruments: List[Dict[str, Any]], spot: float) -> Dict[str, Any]:
    """Fit Heston to a prepared instrument list. See module docstring for the shape."""
    if not _HAVE_SCIPY:
        return {"ok": False, "reason": "scipy unavailable"}
    if len(instruments) < MIN_INSTRUMENTS:
        return {"ok": False, "reason": f"only {len(instruments)} instruments"}

    prices = [ins["price"] for ins in instruments]
    floor = max(0.05, 0.02 * statistics.median(prices))
    x0 = _seed(instruments)

    def residuals(p: Sequence[float]) -> List[float]:
        v0, kappa, theta, xi, rho = p
        return [
            (heston_price(spot, ins["K"], ins["T"], ins["r"], v0, kappa, theta, xi,
                          rho, ins["otype"], ins["q"], gl_n=_GL_CALIB) - ins["price"])
            / (ins["price"] + floor)
            for ins in instruments
        ]

    try:
        res = least_squares(residuals, x0, bounds=(_LO, _HI), method="trf",
                            max_nfev=200, ftol=1e-8, xtol=1e-8)
    except Exception as exc:  # optimiser blew up on a degenerate chain
        return {"ok": False, "reason": f"solve failed: {exc}"}

    v0, kappa, theta, xi, rho = (float(v) for v in res.x)
    params = {"v0": v0, "kappa": kappa, "theta": theta, "xi": xi, "rho": rho}

    errs = _iv_errors(instruments, (v0, kappa, theta, xi, rho), spot)
    iv_rmse = _rmse([e for _, _, e in errs])
    by_exp = {}
    for exp, tenor, e in errs:
        by_exp.setdefault(exp, (tenor, []))[1].append(e)
    per_expiration = sorted(
        ({"expiration": exp.isoformat(), "tenor": round(tenor, 4),
          "n": len(es), "iv_rmse": _rmse(es)}
         for exp, (tenor, es) in by_exp.items()),
        key=lambda d: d["tenor"],
    )

    ok = iv_rmse is not None and iv_rmse < _IV_RMSE_OK
    return {
        "ok": ok,
        "params": params,
        "iv_rmse": iv_rmse,
        "n_instruments": len(instruments),
        "feller_ok": feller_ok(kappa, theta, xi),
        "per_expiration": per_expiration,
        "reason": None if ok else "fit exceeds tolerance",
    }


def calibrate_from_chain(chain: "OptionChain", spot: float, rate_fn: Callable[[float], float],
                         dividend_yield: Optional[float]) -> Dict[str, Any]:
    """Select instruments from a live chain and calibrate."""
    instruments = _select_instruments(chain, spot, rate_fn, dividend_yield or 0.0)
    return calibrate_instruments(instruments, spot)
