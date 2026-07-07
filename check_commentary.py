"""
Verification for the page-commentary reads. Pure functions, no network: the
directional thresholds are exercised on constructed inputs so the lean, the
qualifiers, and the graceful None paths are pinned down.

Run:  python3 check_commentary.py
"""
import sys

from backend.commentary import realized_implied_read

_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


# A calm one-year cone: current realized low in its own range.
CONE_CALM = {"min": 0.06, "p25": 0.09, "median": 0.12, "p75": 0.16, "max": 0.30,
             "current": 0.10, "samples": 252}
# An elevated cone: current realized high in its own range.
CONE_HOT = {"min": 0.06, "p25": 0.09, "median": 0.12, "p75": 0.16, "max": 0.30,
            "current": 0.20, "samples": 252}


hr("Directional lean from the volatility risk premium")

rich = realized_implied_read(0.18, 0.10, CONE_CALM)
check("implied well above realized -> rich", rich["lean"] == "rich", rich["headline"])
check("rich read leans toward selling premium",
      "selling premium" in rich["detail"])
check("rich + calm realized adds the mean-reversion caveat",
      "can rise" in rich["detail"])

# realized_gk20 matches the cone's current value, as it does in production.
cheap = realized_implied_read(0.15, 0.20, CONE_HOT)
check("implied below realized -> cheap", cheap["lean"] == "cheap", cheap["headline"])
check("cheap read leans toward owning optionality",
      "owning optionality" in cheap["detail"])
check("cheap + elevated realized notes movement already high",
      "already elevated" in cheap["detail"])

neutral = realized_implied_read(0.110, 0.105, CONE_CALM)
check("implied roughly in line -> neutral", neutral["lean"] == "neutral",
      f"ratio {0.110 / 0.105:.3f}")
check("neutral read states no edge", "No strong volatility edge" in neutral["detail"])


hr("Threshold boundaries")

at_rich = realized_implied_read(0.1150, 0.10, CONE_CALM)   # ratio exactly 1.15
check("ratio 1.15 counts as rich", at_rich["lean"] == "rich")
at_cheap = realized_implied_read(0.090, 0.10, CONE_CALM)   # ratio exactly 0.90
check("ratio 0.90 counts as cheap", at_cheap["lean"] == "cheap")
just_under = realized_implied_read(0.1149, 0.10, CONE_CALM)  # ratio 1.149
check("ratio just under 1.15 is neutral", just_under["lean"] == "neutral")


hr("Qualifiers and graceful degradation")

flagged = realized_implied_read(0.18, 0.10, CONE_CALM,
                                divergence={"flag": True})
check("divergence flag appends the method-sensitivity note",
      "method-sensitive" in flagged["detail"])
no_flag = realized_implied_read(0.18, 0.10, CONE_CALM,
                                divergence={"flag": False})
check("no divergence flag leaves the read clean",
      "method-sensitive" not in no_flag["detail"])

no_cone = realized_implied_read(0.18, 0.10, None)
check("missing cone still returns a read", no_cone is not None and no_cone["lean"] == "rich")
check("missing cone omits the yearly-range qualifier",
      "quartile" not in no_cone["detail"] and "median" not in no_cone["detail"])

check("missing implied returns None", realized_implied_read(None, 0.10) is None)
check("missing realized returns None", realized_implied_read(0.18, None) is None)
check("zero realized returns None", realized_implied_read(0.18, 0.0) is None)

check("assumption is always stated",
      rich["assumption"].startswith("Assumes") and cheap["assumption"].startswith("Assumes"))


hr("RESULT")
print(f"{len(_PASSES)} passed, {len(_FAILS)} failed")
sys.exit(1 if _FAILS else 0)
