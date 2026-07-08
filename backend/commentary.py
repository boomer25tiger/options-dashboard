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


def term_structure_read(points):
    """
    Shape of the ATM term structure from the raw ATM points. Upward slope prices
    more uncertainty further out; an inverted slope flags near-term stress. The
    ultra-short front (0DTE and 1DTE) is skipped as the front reference where a
    longer point exists, since near-zero-tenor ATM implied is noisy.
    """
    pts = sorted((p["tenor"], p["atm_raw"]) for p in (points or [])
                 if p.get("atm_raw") is not None and p.get("tenor"))
    if len(pts) < 2:
        return None
    front_candidates = [p for p in pts if p[0] >= 0.015]
    front = front_candidates[0] if front_candidates else pts[0]
    back = pts[-1]
    if back[0] <= front[0]:
        return None

    diff = (back[1] - front[1]) * 100.0
    fd, bd = round(front[0] * 365), round(back[0] * 365)
    if diff > 0.5:
        headline = "Upward-sloping term structure"
        interp = ("The market prices more uncertainty further out, with no unusual "
                  "near-term event in the front.")
    elif diff < -0.5:
        headline = "Inverted term structure"
        interp = ("The front expiries carry the higher implied vol, a sign of "
                  "near-term stress or an event priced into the short dates.")
    else:
        headline = "Flat term structure"
        interp = "Implied vol is close across maturities, with no strong calendar tilt."

    move = "rise" if diff >= 0 else "fall"
    detail = (f"ATM implied runs {front[1] * 100:.1f}% at {fd}d and "
              f"{back[1] * 100:.1f}% at {bd}d, a {abs(diff):.1f}-point {move} with "
              f"maturity. {interp}")
    return {"headline": headline, "detail": detail}


def heston_contract_read(price, heston_iv, market_iv, fit_iv_rmse):
    """
    Where a single contract sits against the whole-chain Heston fit. Compares the
    Heston-implied vol with the contract's own market implied vol, and only calls it
    cheap or rich when the gap clears the fit's own error, so surface noise is not
    dressed up as a dislocation.
    """
    if price is None or heston_iv is None or market_iv is None:
        return None
    diff = (heston_iv - market_iv) * 100.0  # vol points, model minus market
    tol = max(0.3, (fit_iv_rmse or 0.0) * 100.0)
    if abs(diff) <= tol:
        return {
            "headline": "In line with the calibrated surface",
            "detail": (f"Heston, fit to the whole chain, values it ${price:.2f}, within "
                       f"the fit's own {tol:.1f} vol-point tolerance of the contract's "
                       f"implied vol. No dislocation against the surface."),
        }
    if diff > 0:
        return {
            "headline": "Screens cheap versus the surface",
            "detail": (f"Heston values it ${price:.2f}, {diff:.1f} vol points above the "
                       f"contract's own implied vol, so the market is pricing it below "
                       f"the surface the model fits."),
        }
    return {
        "headline": "Screens rich versus the surface",
        "detail": (f"Heston values it ${price:.2f}, {abs(diff):.1f} vol points below the "
                   f"contract's own implied vol, so the market is pricing it above the "
                   f"fitted surface."),
    }


def hedge_read(summary):
    """
    Reads a delta-hedging run in terms of the vol spread that drove it. A long
    delta hedge is paid when the path moves more than the implied vol it hedged at;
    a short keeps premium when the path moves less. Splits the result into its
    gamma and theta halves.
    """
    if not summary:
        return None
    pnl = summary.get("total_pnl")
    rv = summary.get("realized_vol")
    iv = summary.get("implied_vol")
    if pnl is None or rv is None or iv is None:
        return None

    long_side = summary.get("position", 1) >= 0
    rv_pct, iv_pct = rv * 100, iv * 100
    above = rv > iv
    money = f"${abs(pnl):,.0f}"
    verb = "earned" if pnl >= 0 else "lost"

    if long_side:
        headline = f"Delta-hedged long {verb} {money}"
        driver = (f"Realized {rv_pct:.1f}% ran {'above' if above else 'below'} the "
                  f"{iv_pct:.1f}% implied it hedged at, and a long delta hedge is paid "
                  f"when the path moves more than priced.")
    else:
        headline = f"Delta-hedged short {verb} {money}"
        driver = (f"Realized {rv_pct:.1f}% ran {'above' if above else 'below'} the "
                  f"{iv_pct:.1f}% implied it sold at, and a short delta hedge keeps "
                  f"premium when the path moves less than priced.")

    gamma = summary.get("gamma_pnl_total")
    theta = summary.get("theta_pnl_total")
    g_word = (f"a gamma gain of {_money(gamma)}" if (gamma or 0) >= 0
              else f"a gamma cost of {_money(gamma)}")
    t_word = (f"a theta gain of {_money(theta)}" if (theta or 0) >= 0
              else f"a theta bleed of {_money(theta)}")
    detail = f"{driver} Over the window that split into {g_word} and {t_word}."
    return {
        "headline": headline,
        "detail": detail,
        "note": "Hedged daily at the implied vol shown, held constant over the window.",
    }


def montecarlo_read(price, ci_low, ci_high, bs):
    """Whether the Monte Carlo interval agrees with the closed-form price."""
    if price is None or bs is None:
        return None
    half = (ci_high - ci_low) / 2.0
    if ci_low <= bs <= ci_high:
        return {
            "headline": "Agrees with the closed form",
            "detail": (f"Monte Carlo prices it ${price:.2f} give or take ${half:.2f} at 95%, "
                       f"and the ${bs:.2f} Black-Scholes value sits inside that band. The "
                       f"simulation and the formula agree, as they should on a vanilla option."),
        }
    return {
        "headline": "Interval misses the closed form",
        "detail": (f"Monte Carlo prices it ${price:.2f} give or take ${half:.2f}, and the "
                   f"${bs:.2f} Black-Scholes value falls outside. More paths would tighten "
                   f"and re-centre the estimate."),
    }


def exotic_read(kind, option_type, price, vanilla, knock_probability=None,
                average=None, barrier_type=None):
    """Reads a path-dependent price against the vanilla on the same strike."""
    if price is None or vanilla is None:
        return None
    cheaper = price < vanilla
    if kind == "asian":
        headline = "Asian prices below the vanilla" if cheaper else "Asian prices near the vanilla"
        detail = (f"The {average} Asian {option_type} prices ${price:.2f} against the "
                  f"${vanilla:.2f} vanilla. Averaging the path dampens the terminal move, so an "
                  f"Asian normally costs less than the plain option on the same strike.")
        return {"headline": headline, "detail": detail}

    kp = f"{knock_probability * 100:.0f}%" if knock_probability is not None else "some"
    knocks_out = bool(barrier_type) and barrier_type.endswith("out")
    headline = "Barrier discounted from the vanilla" if cheaper else "Barrier near the vanilla"
    if knocks_out:
        detail = (f"The {barrier_type} {option_type} prices ${price:.2f} against the ${vanilla:.2f} "
                  f"vanilla, discounted by the {kp} chance of touching the barrier and knocking out.")
    else:
        detail = (f"The {barrier_type} {option_type} prices ${price:.2f} against the ${vanilla:.2f} "
                  f"vanilla, worth only the {kp} of paths that reach the barrier and knock in.")
    return {"headline": headline, "detail": detail}


def realized_history_read(current_implied, fwd_median, above_share, premium, horizon):
    """
    Empirical vol-risk premium: how the current implied compares with the realized
    vol that actually followed over the past year, and how often it sat above it.
    """
    if current_implied is None or fwd_median is None or above_share is None:
        return None
    imp, med = current_implied * 100, fwd_median * 100
    prem = (premium or 0.0) * 100
    share = above_share * 100
    if above_share >= 0.6 and (premium or 0) > 0.005:
        headline = "Implied has tended to overprice subsequent realized"
        lean = "options screen rich against what realized has actually delivered"
    elif above_share <= 0.4:
        headline = "Implied has tended to underprice subsequent realized"
        lean = "options screen cheap against what realized has actually delivered"
    else:
        headline = "Implied roughly tracks subsequent realized"
        lean = "no strong empirical premium either way"
    detail = (f"Current one-month implied is {imp:.1f}%. Over the past year, the {horizon}-day "
              f"realized that followed averaged {med:.1f}%, and today's implied sits above "
              f"{share:.0f}% of those outcomes, an empirical premium of {prem:+.1f} points. So "
              f"{lean}.")
    return {
        "headline": headline,
        "detail": detail,
        "note": f"Forward realized is the vol that materialized over the {horizon} trading days after each past date.",
    }
