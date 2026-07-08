"""
Verification for the page-commentary reads. Pure functions, no network: the
directional thresholds are exercised on constructed inputs so the lean, the
qualifiers, and the graceful None paths are pinned down.

Run:  python3 check_commentary.py
"""
import sys

from backend.commentary import (
    contract_read, exotic_read, hedge_read, heston_contract_read, montecarlo_read,
    realized_history_read, realized_implied_read, strategy_read, term_structure_read,
)

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


hr("Contract read: early exercise and breakeven")

# In-the-money put on a dividend payer, with a real early-exercise premium.
PUT = {"type": "put", "spot": 750.0, "dividend_yield": 0.012,
       "pricing": {"black_scholes": 12.00, "binomial_american": 12.40,
                   "early_exercise_premium": 0.40},
       "probability": {"prob_itm": 0.55, "prob_of_profit": 0.48, "breakeven": 735.0}}
# Call on a no-dividend underlying, American equals European.
CALL = {"type": "call", "spot": 750.0, "dividend_yield": 0.0,
        "pricing": {"black_scholes": 9.00, "binomial_american": 9.001,
                    "early_exercise_premium": 0.001},
        "probability": {"prob_itm": 0.42, "prob_of_profit": 0.37, "breakeven": 759.0}}

put = contract_read(PUT, "SPY")
check("ITM put with a gap reads early exercise as valuable",
      put["pricing"]["headline"] == "Early exercise carries value")
check("early-exercise dollars keep cents precision",
      "$0.40 above" in put["pricing"]["detail"], put["pricing"]["detail"])
check("put early-exercise context mentions the strike's time value",
      "time value of money on the strike" in put["pricing"]["detail"])
check("put breakeven read points downward",
      put["probability"]["headline"] == "Profits if SPY finishes below 735.00"
      and "must fall" in put["probability"]["detail"], put["probability"]["detail"])
check("put probability names ITM and profit odds",
      "55% modeled chance" in put["probability"]["detail"]
      and "48% of profit" in put["probability"]["detail"])

call = contract_read(CALL, "SPY")
check("no-dividend call shows no early-exercise value",
      call["pricing"]["headline"] == "Early exercise adds nothing here")
check("call breakeven read points upward",
      call["probability"]["headline"] == "Profits if SPY finishes above 759.00"
      and "must rise" in call["probability"]["detail"])

check("missing detail returns None", contract_read(None) is None)
check("detail without pricing or probability returns None",
      contract_read({"type": "call", "pricing": {}, "probability": {}}) is None)


hr("Term-structure read: slope of ATM implied by maturity")

def _tp(tenor, iv):
    return {"tenor": tenor, "atm_raw": iv}

up = term_structure_read([_tp(0.02, 0.10), _tp(0.08, 0.12), _tp(0.25, 0.15)])
check("rising ATM by maturity reads as upward-sloping",
      up["headline"] == "Upward-sloping term structure", up["detail"])
check("upward detail names both ends and the rise",
      "10.0% at 7d" in up["detail"] and "15.0% at 91d" in up["detail"]
      and "5.0-point rise" in up["detail"])

inv = term_structure_read([_tp(0.02, 0.20), _tp(0.25, 0.14)])
check("falling ATM by maturity reads as inverted",
      inv["headline"] == "Inverted term structure" and "fall" in inv["detail"], inv["detail"])

flat = term_structure_read([_tp(0.02, 0.120), _tp(0.25, 0.122)])
check("near-equal ATM reads as flat", flat["headline"] == "Flat term structure")

skip = term_structure_read([_tp(0.001, 0.04), _tp(0.05, 0.12), _tp(0.25, 0.15)])
check("noisy 0DTE front is skipped for the front reference",
      "12.0% at 18d" in skip["detail"] and "4.0%" not in skip["detail"], skip["detail"])

check("single point returns None", term_structure_read([_tp(0.05, 0.12)]) is None)
check("no points returns None", term_structure_read([]) is None)


hr("Heston contract read: contract versus the calibrated surface")

# fit RMSE 1.4 vol points -> tolerance band 1.4 vol points.
inline = heston_contract_read(5.44, 0.1505, 0.1477, 0.014)
check("gap inside the fit tolerance reads as in line",
      inline["headline"] == "In line with the calibrated surface", inline["detail"])

rich = heston_contract_read(10.52, 0.1238, 0.1422, 0.014)
check("market vol above the Heston fit screens rich",
      rich["headline"] == "Screens rich versus the surface"
      and "1.8 vol points below" in rich["detail"], rich["detail"])

cheap = heston_contract_read(3.0, 0.180, 0.150, 0.014)
check("market vol below the Heston fit screens cheap",
      cheap["headline"] == "Screens cheap versus the surface"
      and "3.0 vol points above" in cheap["detail"], cheap["detail"])

check("missing Heston price returns None", heston_contract_read(None, 0.15, 0.15, 0.01) is None)
check("missing market iv returns None", heston_contract_read(5.0, 0.15, None, 0.01) is None)


hr("Hedge read: vol spread and the gamma-theta split")

long_win = hedge_read({"total_pnl": 409.0, "realized_vol": 0.151, "implied_vol": 0.119,
                       "position": 1, "gamma_pnl_total": 1266.0, "theta_pnl_total": -1040.0})
check("long hedge that profited reads as earned",
      long_win["headline"] == "Delta-hedged long earned $409"
      and "ran above" in long_win["detail"], long_win["detail"])
check("long split shows gamma gain and theta bleed",
      "gamma gain of $1,266" in long_win["detail"] and "theta bleed of $1,040" in long_win["detail"])

short_win = hedge_read({"total_pnl": 916.0, "realized_vol": 0.151, "implied_vol": 0.20,
                        "position": -1, "gamma_pnl_total": -827.0, "theta_pnl_total": 1806.0})
check("short hedge that profited reads as earned",
      short_win["headline"] == "Delta-hedged short earned $916"
      and "ran below" in short_win["detail"], short_win["detail"])
check("short split shows gamma cost and theta gain",
      "gamma cost of $827" in short_win["detail"] and "theta gain of $1,806" in short_win["detail"])

check("missing summary returns None", hedge_read(None) is None)
check("missing realized vol returns None",
      hedge_read({"total_pnl": 1, "implied_vol": 0.2, "position": 1}) is None)


hr("Monte Carlo reads")

agree = montecarlo_read(12.45, 12.36, 12.53, 12.47)
check("closed form inside the interval reads as agreement",
      agree["headline"] == "Agrees with the closed form", agree["detail"])
miss = montecarlo_read(12.45, 12.44, 12.46, 12.90)
check("closed form outside the interval is flagged",
      miss["headline"] == "Interval misses the closed form")
check("missing Black-Scholes returns None", montecarlo_read(1.0, 0.9, 1.1, None) is None)

asian = exotic_read("asian", "call", 9.36, 16.22, average="arithmetic")
check("cheaper Asian reads below the vanilla",
      asian["headline"] == "Asian prices below the vanilla"
      and "Averaging the path" in asian["detail"], asian["detail"])

ko = exotic_read("barrier", "call", 9.18, 16.22, knock_probability=0.112,
                 barrier_type="up-and-out")
check("knock-out barrier reads as discounted with its knock chance",
      ko["headline"] == "Barrier discounted from the vanilla"
      and "11% chance" in ko["detail"] and "knocking out" in ko["detail"], ko["detail"])
ki = exotic_read("barrier", "call", 7.10, 16.22, knock_probability=0.112,
                 barrier_type="up-and-in")
check("knock-in barrier reads as worth only the touching paths",
      "knock in" in ki["detail"] and "11%" in ki["detail"])
check("missing exotic price returns None", exotic_read("asian", "call", None, 10.0) is None)


hr("Realized-history read: empirical volatility-risk premium")

rich = realized_history_read(0.144, 0.118, 0.81, 0.026, 21)
check("implied above most forward-realized reads as overpricing",
      rich["headline"] == "Implied has tended to overprice subsequent realized", rich["detail"])
check("rich detail carries the numbers",
      "14.4%" in rich["detail"] and "11.8%" in rich["detail"]
      and "above 81%" in rich["detail"] and "+2.6 points" in rich["detail"])

cheap = realized_history_read(0.10, 0.15, 0.25, -0.05, 21)
check("implied below most forward-realized reads as underpricing",
      cheap["headline"] == "Implied has tended to underprice subsequent realized")
mid = realized_history_read(0.13, 0.128, 0.5, 0.002, 21)
check("implied near the middle reads as roughly tracking",
      mid["headline"] == "Implied roughly tracks subsequent realized")

check("missing forward median returns None", realized_history_read(0.14, None, 0.8, 0.02, 21) is None)


hr("RESULT")
print(f"{len(_PASSES)} passed, {len(_FAILS)} failed")
sys.exit(1 if _FAILS else 0)
