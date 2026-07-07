"""
Verification for the Heston calibration (backend/heston_calib.py).

Builds a synthetic option set priced from KNOWN Heston parameters, then checks the
calibrator recovers a model that reprices that set to within a fraction of a vol
point and lands the identifiable parameters near the truth. Also checks the
graceful-degradation path.

Run:  python3 check_heston_calib.py
"""
import datetime as dt
import sys

from backend.heston_calib import calibrate_instruments, MIN_INSTRUMENTS
from heston import heston_price
from pricing_engine import implied_vol

_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


SPOT, R, Q = 100.0, 0.02, 0.0
TRUE = dict(v0=0.045, kappa=1.8, theta=0.055, xi=0.45, rho=-0.65)
BASE = dt.date(2026, 7, 7)


def build_instruments():
    instruments = []
    for T in (0.1, 0.25, 0.5, 1.0):
        exp = BASE + dt.timedelta(days=round(T * 365))
        for k in (0.88, 0.92, 0.96, 1.0, 1.04, 1.08, 1.12):
            K = SPOT * k
            otype = "call" if K >= SPOT else "put"
            price = heston_price(SPOT, K, T, R, TRUE["v0"], TRUE["kappa"],
                                 TRUE["theta"], TRUE["xi"], TRUE["rho"], otype, Q)
            iv = implied_vol(price, SPOT, K, T, R, otype, Q)
            if iv is None:
                continue
            instruments.append({"K": K, "T": T, "r": R, "q": Q, "otype": otype,
                                "price": price, "iv": iv, "expiration": exp})
    return instruments


hr("Recover known parameters from synthetic Heston prices")
instruments = build_instruments()
print(f"  built {len(instruments)} synthetic instruments")
result = calibrate_instruments(instruments, SPOT)
check("calibration reports ok", result.get("ok") is True, result.get("reason") or "")
p = result.get("params", {})
print(f"  recovered: v0={p.get('v0'):.4f} kappa={p.get('kappa'):.3f} "
      f"theta={p.get('theta'):.4f} xi={p.get('xi'):.3f} rho={p.get('rho'):.3f}")
print(f"  truth:     v0={TRUE['v0']:.4f} kappa={TRUE['kappa']:.3f} "
      f"theta={TRUE['theta']:.4f} xi={TRUE['xi']:.3f} rho={TRUE['rho']:.3f}")
print(f"  iv_rmse = {result.get('iv_rmse'):.5f}")

check("repricing fit under 0.5 vol point", result.get("iv_rmse") < 0.005,
      f"iv_rmse {result.get('iv_rmse'):.5f}")
check("initial variance recovered near truth", abs(p.get("v0") - TRUE["v0"]) < 0.01)
check("long-run variance recovered near truth", abs(p.get("theta") - TRUE["theta"]) < 0.02)
check("correlation recovered near truth", abs(p.get("rho") - TRUE["rho"]) < 0.12,
      f"rho {p.get('rho'):.3f} vs {TRUE['rho']}")
check("instrument count reported", result.get("n_instruments") == len(instruments))
check("feller flag present", isinstance(result.get("feller_ok"), bool))
check("per-expiration fit has an entry per maturity",
      len(result.get("per_expiration", [])) == 4)


hr("Graceful degradation")
few = calibrate_instruments(instruments[:MIN_INSTRUMENTS - 1], SPOT)
check("too few instruments returns ok=False", few.get("ok") is False, few.get("reason"))
check("no instruments returns ok=False", calibrate_instruments([], SPOT).get("ok") is False)


hr("RESULT")
print(f"{len(_PASSES)} passed, {len(_FAILS)} failed")
sys.exit(1 if _FAILS else 0)
