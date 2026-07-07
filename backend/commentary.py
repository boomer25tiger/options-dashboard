"""
Page commentary: deterministic 'reads' that turn already-computed metrics into a
short directional interpretation. Each read is a pure function of values shown on
the page, tied to specific numbers, with the assumption stated and no explicit buy
or sell. Thresholds live as module constants so they are easy to tune and test.
"""

# Volatility-risk-premium bands, expressed as the implied/realized ratio.
_RICH_RATIO = 1.15   # implied at least 15% above realized -> options screen rich
_CHEAP_RATIO = 0.90  # implied at least 10% below realized -> options screen cheap


def _pts(x):
    """Vol points from a decimal vol (0.151 -> 15.1)."""
    return x * 100.0


def _cone_bucket(current, cone20):
    """Where current realized sits within its own one-year distribution."""
    if not cone20:
        return None
    if current <= cone20["p25"]:
        return "low"
    if current <= cone20["median"]:
        return "below_median"
    if current < cone20["p75"]:
        return "above_median"
    return "high"


def realized_implied_read(atm_iv, realized_gk20, cone20=None, divergence=None):
    """
    Directional read for the Realized vs Implied page. Compares ATM implied with
    20-day Garman-Klass realized (the volatility risk premium), qualifies the lean
    by where realized sits in its own yearly range, and softens it when the two
    realized estimators disagree. Returns None when the inputs are missing.
    """
    if not atm_iv or not realized_gk20 or realized_gk20 <= 0:
        return None

    ratio = atm_iv / realized_gk20
    spread_pts = _pts(atm_iv - realized_gk20)
    lean = "rich" if ratio >= _RICH_RATIO else "cheap" if ratio <= _CHEAP_RATIO else "neutral"

    direction = "above" if spread_pts >= 0 else "below"
    core = (f"Implied {_pts(atm_iv):.1f}% runs {abs(spread_pts):.1f} points "
            f"{direction} 20-day realized (Garman-Klass)")

    bucket = _cone_bucket(realized_gk20, cone20)
    ctx = {
        "low": ", and realized sits in the lower quartile of its past year",
        "below_median": ", and realized sits below its yearly median",
        "above_median": ", and realized sits above its yearly median",
        "high": ", and realized sits in the upper quartile of its past year",
    }.get(bucket, "")

    if lean == "rich":
        headline = "Options screen rich versus recent movement"
        verdict = "The read leans toward selling premium"
        if bucket in ("low", "below_median"):
            verdict += ", with the caveat that unusually calm realized can rise"
    elif lean == "cheap":
        headline = "Options screen cheap versus recent movement"
        verdict = "The read leans toward owning optionality"
        if bucket in ("high", "above_median"):
            verdict += ", since recent movement is already elevated"
    else:
        headline = "Implied and realized are roughly in line"
        verdict = "No strong volatility edge either way"

    detail = f"{core}{ctx}. {verdict}."
    if divergence and divergence.get("flag"):
        detail += (" Garman-Klass and close-to-close disagree at 20 days, so the "
                   "realized figure is method-sensitive and the read less certain.")

    return {
        "lean": lean,
        "headline": headline,
        "detail": detail,
        "assumption": "Assumes the coming weeks resemble recent realized.",
    }
