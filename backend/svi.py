"""
SVI (stochastic volatility inspired) slice calibration.

Fits Gatheral's raw SVI to one expiration's total-implied-variance smile:
    w(k) = a + b * ( rho*(k - m) + sqrt((k - m)^2 + sigma^2) )
where k = log(K / forward) and w = IV^2 * T (total implied variance).

The fit is per-slice and degrades gracefully: it returns None on too-few points,
failure to converge, degenerate parameters, or a poor residual, so callers hide
the overlay for that slice rather than show a distorted fit.

Note for later context: SVI and the planned Heston extension both fit a parametric
model to the chain, but they remain separate features.
"""
import math

try:
    import numpy as np
    from scipy.optimize import least_squares
    _HAVE = True
except Exception:  # pragma: no cover - scipy/numpy expected present
    _HAVE = False

MIN_POINTS = 6


def total_variance(a, b, rho, m, sigma, k):
    """Raw-SVI total implied variance at log-moneyness k."""
    return a + b * (rho * (k - m) + math.sqrt((k - m) ** 2 + sigma ** 2))


def iv_from_params(params, k, T):
    """Fitted implied vol at log-moneyness k for a slice of maturity T."""
    if T <= 0:
        return None
    w = total_variance(params["a"], params["b"], params["rho"],
                       params["m"], params["sigma"], k)
    return math.sqrt(w / T) if w > 0 else None


def fit_slice(ks, ws):
    """
    Calibrate raw SVI to (log-moneyness, total-variance) points. Returns a params
    dict {a,b,rho,m,sigma,rmse,n} or None when the fit is unavailable or poor.
    """
    if not _HAVE or len(ks) < MIN_POINTS:
        return None
    ks = np.asarray(ks, dtype=float)
    ws = np.asarray(ws, dtype=float)
    mask = ws > 0
    ks, ws = ks[mask], ws[mask]
    if len(ks) < MIN_POINTS:
        return None

    w_med = float(np.median(ws))
    k_span = float(np.ptp(ks)) or 1.0
    b0 = float(np.ptp(ws)) / k_span
    x0 = [max(float(np.min(ws)) * 0.5, 1e-8), max(b0, 1e-3), -0.4, 0.0, 0.1]
    lo = [-abs(w_med) - 1e-6, 0.0, -0.999, -1.0, 1e-4]
    hi = [np.inf, 10.0, 0.999, 1.0, 5.0]

    # Relative residuals so the small at-the-money variances are not swamped by the
    # larger wings (which would otherwise pull the ATM fit off, badly for short T).
    w_floor = max(1e-6, 0.1 * w_med)

    def model_w(p):
        a, b, rho, m, sig = p
        return a + b * (rho * (ks - m) + np.sqrt((ks - m) ** 2 + sig ** 2))

    def resid(p):
        return (model_w(p) - ws) / (ws + w_floor)

    try:
        res = least_squares(resid, x0, bounds=(lo, hi), max_nfev=600)
    except Exception:
        return None
    if not res.success and res.status <= 0:
        return None

    a, b, rho, m, sig = (float(v) for v in res.x)
    abs_res = model_w(res.x) - ws
    rel_rmse = float(np.sqrt(np.mean(((abs_res) / (ws + w_floor)) ** 2)))
    if rel_rmse > 0.5:  # a clearly distorted fit; hide this slice
        return None
    return {"a": a, "b": b, "rho": rho, "m": m, "sigma": sig,
            "rmse": float(np.sqrt(np.mean(abs_res ** 2))), "n": int(len(ks))}
