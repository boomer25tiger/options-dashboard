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


def _money(x):
    return f"${abs(x):,.0f}"


# Below this dollar sensitivity a position carries no meaningful exposure on that
# axis, so it reads as neutral rather than being labelled by a rounding residual.
_SENS_FLOOR = 1.0


def strategy_read(summary, spot, ticker="the underlying"):
    """
    Directional read for the Strategy builder. Names the risk character (defined
    or open-ended), the dominant exposure (directional vs volatility, decided by
    the dollar impact of a one-unit move in each factor), and the carry from
    theta, all tied to the position's own numbers. Returns None when the position
    has not priced. Greeks are expected already display-scaled (vega per vol
    point, theta per day), as the service returns them.
    """
    if not summary or not spot:
        return None
    g = summary.get("greeks") or {}
    delta, vega, theta = g.get("delta"), g.get("vega"), g.get("theta")
    net_cost = summary.get("net_cost")
    mp, ml = summary.get("max_profit"), summary.get("max_loss")
    pop = summary.get("prob_of_profit")
    if delta is None and vega is None:
        return None

    dir_sens = abs(delta) * spot * 0.01 if delta is not None else 0.0
    vol_sens = abs(vega) if vega is not None else 0.0
    defined = ml is not None and mp is not None
    flag = None if ml is not None else "risk"

    if max(dir_sens, vol_sens) < _SENS_FLOOR:
        theme = "neutral"
    elif dir_sens >= vol_sens:
        theme = "bull" if (delta or 0) > 0 else "bear"
    else:
        theme = "longvol" if (vega or 0) > 0 else "shortvol"

    # Risk character keys off the downside alone: a long option has a bounded loss
    # and open-ended profit, which is defined risk, not open risk.
    risk_word = "Defined-risk" if ml is not None else "Open-risk"
    theme_phrase = {
        "bull": "directional position with a bullish tilt",
        "bear": "directional position with a bearish tilt",
        "longvol": "long-volatility position",
        "shortvol": "short-volatility position",
        "neutral": "market-neutral position",
    }[theme]
    headline = f"{risk_word} {theme_phrase}"

    bits = []
    if net_cost is not None:
        bits.append(f"{_money(net_cost)} net {'debit' if net_cost > 0 else 'credit'}")
    if defined and ml:
        bits.append(f"defined risk with max loss {_money(ml)} against max profit "
                    f"{_money(mp)}, reward-to-risk {mp / abs(ml):.2f} to 1")
    elif ml is None:
        bits.append("open-ended downside, so size it deliberately")
    elif mp is None:
        bits.append(f"defined risk of {_money(ml)} with open-ended upside")
    if pop is not None:
        bits.append(f"a {pop * 100:.0f}% modeled chance of profit")
    risk_sentence = ", ".join(bits)

    if theme in ("bull", "bear"):
        lead = (f"Net {'long' if (delta or 0) > 0 else 'short'} delta, so a 1% move "
                f"in {ticker} is worth about {_money(dir_sens)}")
    elif theme in ("longvol", "shortvol"):
        moves = "rises" if theme == "longvol" else "falls"
        lead = (f"Net {'long' if (vega or 0) > 0 else 'short'} vega, so it gains if "
                f"implied vol {moves}, worth about {_money(vol_sens)} per volatility point")
    else:
        lead = "Little net directional or volatility exposure"

    carry = ""
    if theta is not None and abs(theta) > 0.01:
        carry = (f", while time decay works {'in your favor' if theta > 0 else 'against you'} "
                 f"near {_money(theta)} a day")

    detail = f"{risk_sentence}. {lead}{carry}."

    return {
        "flag": flag,
        "theme": theme,
        "headline": headline,
        "detail": detail,
        "note": "Probability of profit is modeled under the current implied vol.",
    }


def _pricing_read(pricing, otype, q):
    """Early-exercise interpretation from the binomial-minus-Black-Scholes gap."""
    bs = pricing.get("black_scholes")
    eep = pricing.get("early_exercise_premium")
    if bs is None or eep is None:
        return None
    if eep <= 0.005:
        return {
            "headline": "Early exercise adds nothing here",
            "detail": ("The binomial American price matches Black-Scholes to within "
                       "half a cent, so early exercise carries no value and the "
                       "European formula is a fine approximation for this contract."),
        }
    pct_str = f", about {eep / bs * 100:.0f}% of its value" if bs and bs > 0 else ""
    if otype == "put":
        context = ("Puts earn this deep in the money, where exercising early frees "
                   "the time value of money on the strike.")
    elif otype == "call" and q > 0:
        context = ("For a call it comes from dividends, where exercising early "
                   "captures a payout the holder would otherwise miss.")
    else:
        context = "It measures the value of the right to exercise before expiry."
    return {
        "headline": "Early exercise carries value",
        "detail": (f"The American binomial price sits ${eep:.2f} above "
                   f"Black-Scholes{pct_str}, the premium for the right to exercise "
                   f"before expiry. {context}"),
    }


def _probability_read(prob, spot, otype, ticker):
    """Breakeven distance and modeled probabilities for a single option."""
    be = prob.get("breakeven")
    p_itm = prob.get("prob_itm")
    pop = prob.get("prob_of_profit")
    if be is None and p_itm is None and pop is None:
        return None

    headline = "Breakeven and probability"
    s1 = ""
    if be is not None and spot:
        move_pct = abs(be - spot) / spot * 100.0
        side = "above" if be >= spot else "below"
        verb = "rise" if otype == "call" else "fall"
        headline = f"Profits if {ticker} finishes {side} {be:.2f}"
        s1 = (f"Breakeven {be:.2f} sits {move_pct:.1f}% {side} spot, so {ticker} must "
              f"{verb} that far by expiry to profit. ")

    if p_itm is not None and pop is not None:
        s2 = (f"A {p_itm * 100:.0f}% modeled chance of finishing in the money, and "
              f"{pop * 100:.0f}% of profit after the premium.")
    elif p_itm is not None:
        s2 = f"A {p_itm * 100:.0f}% modeled chance of finishing in the money."
    elif pop is not None:
        s2 = f"A {pop * 100:.0f}% modeled chance of profit after the premium."
    else:
        s2 = ""

    return {"headline": headline, "detail": (s1 + s2).strip()}


def contract_read(detail, ticker="the underlying"):
    """
    Reads for the Contract page, one per tab. `pricing` interprets the
    early-exercise premium; `probability` interprets the breakeven distance and the
    modeled odds. Either may be None when its inputs are missing.
    """
    if not detail:
        return None
    otype = detail.get("type")
    pricing = _pricing_read(detail.get("pricing") or {}, otype,
                            detail.get("dividend_yield") or 0.0)
    probability = _probability_read(detail.get("probability") or {},
                                    detail.get("spot"), otype, ticker)
    if pricing is None and probability is None:
        return None
    return {"pricing": pricing, "probability": probability}
