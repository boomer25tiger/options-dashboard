"""
Verification for the page-commentary reads. Pure functions, no network: the
directional thresholds are exercised on constructed inputs so the lean, the
qualifiers, and the graceful None paths are pinned down.

Run:  python3 check_commentary.py
"""
import sys

from backend.commentary import realized_implied_read, strategy_read

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


# Live-shaped strategy summaries (greeks already display-scaled: vega per vol
# point, theta per day), taken from real SPY responses.
BULL = {"net_cost": 765.92,
        "greeks": {"delta": 20.98, "gamma": -0.044, "vega": 3.60, "theta": -3.27, "rho": 12.74},
        "breakevens": [752.66], "max_profit": 734.08, "max_loss": -765.92,
        "prob_of_profit": 0.4552}
STRADDLE = {"net_cost": -2370.68,
            "greeks": {"delta": -1.36, "gamma": -2.68, "vega": -174.24, "theta": 37.88, "rho": 1.16},
            "breakevens": [726.29, 773.71], "max_profit": 2370.68, "max_loss": None,
            "prob_of_profit": 0.5737}
LONG_CALL = {"net_cost": 300.0,
             "greeks": {"delta": 50.0, "gamma": 0.5, "vega": 15.0, "theta": -8.0, "rho": 4.0},
             "breakevens": [753.0], "max_profit": None, "max_loss": -300.0,
             "prob_of_profit": 0.40}


hr("Strategy read: dominant exposure and risk character")

bull = strategy_read(BULL, 750.0, "SPY")
check("directional position reads as a bullish tilt", bull["theme"] == "bull", bull["headline"])
check("bounded loss reads as defined risk", bull["headline"].startswith("Defined-risk"))
check("bull detail names the debit and reward-to-risk",
      "net debit" in bull["detail"] and "reward-to-risk" in bull["detail"])
check("bull detail translates delta into a dollar move",
      "1% move in SPY is worth about $157" in bull["detail"], bull["detail"])
check("bull carries no open-ended-risk flag", bull["flag"] is None)

straddle = strategy_read(STRADDLE, 750.0, "SPY")
check("vol-dominated short premium reads as short-volatility",
      straddle["theme"] == "shortvol", straddle["headline"])
check("unbounded loss flags open risk",
      straddle["flag"] == "risk" and straddle["headline"].startswith("Open-risk"))
check("straddle names the credit and open-ended downside",
      "net credit" in straddle["detail"] and "open-ended downside" in straddle["detail"])
check("straddle: short vega gains if implied vol falls",
      "short vega" in straddle["detail"] and "implied vol falls" in straddle["detail"])
check("straddle: positive theta reads as carry in your favor",
      "in your favor" in straddle["detail"])

lc = strategy_read(LONG_CALL, 750.0, "SPY")
check("long call keeps defined risk with open-ended upside",
      lc["headline"].startswith("Defined-risk") and lc["flag"] is None
      and "open-ended upside" in lc["detail"], lc["detail"])

flat = strategy_read({"net_cost": 5.0, "greeks": {"delta": 0.2, "vega": 0.1, "theta": 0.0},
                      "max_profit": 50.0, "max_loss": -50.0, "prob_of_profit": 0.5}, 100.0)
check("negligible exposures read as market-neutral", flat["theme"] == "neutral", flat["headline"])

check("missing summary returns None", strategy_read(None, 750.0) is None)
check("missing spot returns None", strategy_read(BULL, None) is None)
check("summary without greeks returns None",
      strategy_read({"greeks": {}, "net_cost": 1}, 750.0) is None)
check("strategy note states the probability assumption",
      bull["note"].startswith("Probability of profit is modeled"))


hr("RESULT")
print(f"{len(_PASSES)} passed, {len(_FAILS)} failed")
sys.exit(1 if _FAILS else 0)
