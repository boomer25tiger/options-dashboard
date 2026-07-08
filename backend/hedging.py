"""
Delta-hedging simulation.

Takes a real historical price path, opens an option position at a chosen implied
vol, and delta-hedges it day by day through a self-financing cash account (option
mark, stock hedge, and financing/dividend carry). The running portfolio value is
the cumulative hedge P&L, and it started at zero, so the number at expiry is the
total P&L of having hedged that option over that window.

The point it makes: a delta-hedged option converts the gap between the vol you paid
(implied) and the vol the path delivered (realized) into P&L. A long, delta-hedged
option is long gamma and pays theta, so it profits when realized vol beats implied
and bleeds when it does not. Each day is split into its gamma gain and theta bleed
so the tradeoff is legible.

Pure Python over pricing_engine, no third-party deps.
"""
import math
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pricing_engine import bs_greeks, bs_price  # noqa: E402


def realized_vol(closes, steps_per_year=252):
    """Close-to-close annualised realized vol of the path."""
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i] > 0 and closes[i - 1] > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var * steps_per_year)


def _expiry_delta(spot, strike, option_type):
    if option_type == "call":
        return 1.0 if spot > strike else 0.0
    return -1.0 if spot < strike else 0.0


def simulate(closes, sigma_imp, r, q=0.0, option_type="call", position=1,
             moneyness=1.0, quantity=1, steps_per_year=252, multiplier=100):
    """
    Simulate delta-hedging one option over the price path `closes`.

    closes       daily closes from open (index 0) to expiry (last index)
    sigma_imp    implied vol the option is priced and hedged at, held constant
    position     +1 long the option, -1 short it
    moneyness    strike / initial spot (1.0 = at the money at open)

    Returns {"steps": [...per day...], "summary": {...}}. Dollar figures are for
    `quantity` contracts of `multiplier` shares each.
    """
    if len(closes) < 3 or sigma_imp <= 0:
        return None
    otype = option_type.lower()
    pos = 1 if position >= 0 else -1
    mult = multiplier * quantity
    n = len(closes) - 1
    total_t = n / steps_per_year
    dt = 1.0 / steps_per_year
    strike = closes[0] * moneyness

    def price_and_greeks(spot, tau):
        if tau <= 0:
            intrinsic = max(0.0, (spot - strike) if otype == "call" else (strike - spot))
            return intrinsic, _expiry_delta(spot, strike, otype), 0.0, 0.0
        g = bs_greeks(spot, strike, tau, r, sigma_imp, otype, q)
        v = bs_price(spot, strike, tau, r, sigma_imp, otype, q)
        return v, g["delta"], g["gamma"], g["theta"]

    spot0 = closes[0]
    v0, d0, gamma0, theta0 = price_and_greeks(spot0, total_t)
    hedge = -pos * d0                     # shares per contract-share to neutralise delta
    cash = -(pos * v0 + hedge * spot0) * mult   # self-financing: portfolio starts at 0
    entry_premium = pos * v0 * mult       # signed cash effect of taking the position

    steps = [{
        "i": 0, "spot": round(spot0, 4), "tau": round(total_t, 5),
        "option_value": round(v0, 4), "delta": round(d0, 4),
        "hedge_shares": round(hedge * mult, 3), "cum_pnl": 0.0,
        "gamma_pnl": 0.0, "theta_pnl": 0.0,
    }]

    gamma_prev, theta_prev, spot_prev = gamma0, theta0, spot0
    gamma_total = theta_total = 0.0
    for i in range(1, n + 1):
        spot = closes[i]
        tau = max(0.0, total_t - i * dt)
        # carry over the step: interest on cash, dividend on the shares held
        cash *= math.exp(r * dt)
        cash += hedge * mult * spot_prev * q * dt
        v, delta, gamma, theta = price_and_greeks(spot, tau)
        new_hedge = -pos * delta
        cash += -(new_hedge - hedge) * mult * spot   # rebalance trade at today's price
        hedge = new_hedge

        cum_pnl = pos * v * mult + hedge * mult * spot + cash
        d_spot = spot - spot_prev
        gamma_pnl = pos * 0.5 * gamma_prev * (d_spot ** 2) * mult
        theta_pnl = pos * theta_prev * dt * mult
        gamma_total += gamma_pnl
        theta_total += theta_pnl

        steps.append({
            "i": i, "spot": round(spot, 4), "tau": round(tau, 5),
            "option_value": round(v, 4), "delta": round(delta, 4),
            "hedge_shares": round(hedge * mult, 3), "cum_pnl": round(cum_pnl, 2),
            "gamma_pnl": round(gamma_pnl, 2), "theta_pnl": round(theta_pnl, 2),
        })
        gamma_prev, theta_prev, spot_prev = gamma, theta, spot

    total_pnl = steps[-1]["cum_pnl"]
    rvol = realized_vol(closes, steps_per_year)
    summary = {
        "total_pnl": total_pnl,
        "entry_premium": round(entry_premium, 2),
        "implied_vol": sigma_imp,
        "realized_vol": rvol,
        "vol_spread": (sigma_imp - rvol) if rvol is not None else None,
        "gamma_pnl_total": round(gamma_total, 2),
        "theta_pnl_total": round(theta_total, 2),
        "strike": round(strike, 4),
        "position": pos,
        "option_type": otype,
        "days": n,
        "multiplier": mult,
    }
    return {"steps": steps, "summary": summary}
