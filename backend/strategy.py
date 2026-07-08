"""
Multi-leg strategy math on top of the pricing engine.

The engine prices single contracts; this module aggregates legs into a position:
net Greeks (signed-quantity sum), the combined P&L profile at expiry AND at dates
before expiry (time-aware, repriced via the engine), numerical breakevens, max
profit / max loss with unbounded detection, and probability of profit under the
lognormal model. The engine stays the single source of truth for all pricing.

Repricing uses Black-Scholes (European), matching the analytical-Greeks display
default. The Contract page shows the binomial American price separately.

Conventions:
  quantity   : signed; positive = long, negative = short. Contracts for options,
               shares for a stock leg.
  multiplier : 100 for options, 1 for stock (set when the leg is built).
  entry_price: premium per share paid/received; per-share price for a stock leg.
               If None, the current theoretical value is used as the basis.
  P&L is in dollars for the whole position: quantity * multiplier * (value - entry).
"""
import datetime as dt
import os
import sys
from dataclasses import dataclass
from typing import Callable, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pricing_engine import bs_greeks, bs_price, prob_itm  # noqa: E402

from backend.data.normalize import time_to_expiry


@dataclass
class Leg:
    option_type: str                    # 'call' | 'put' | 'stock'
    quantity: int                       # signed: + long, - short
    strike: Optional[float] = None
    expiration: Optional[dt.date] = None
    sigma: Optional[float] = None        # IV for option legs
    entry_price: Optional[float] = None  # per-share basis; None -> theoretical
    multiplier: int = 100

    def is_option(self):
        return self.option_type in ("call", "put")


@dataclass
class MarketContext:
    spot: float
    now: dt.datetime
    rate_fn: Callable[[float], float]    # T (years) -> annual rate
    dividend_yield: float = 0.0


# ----------------------------------------------------------------------
# Per-leg helpers
# ----------------------------------------------------------------------
def _intrinsic(leg, S):
    if leg.option_type == "call":
        return max(S - leg.strike, 0.0)
    if leg.option_type == "put":
        return max(leg.strike - S, 0.0)
    return S  # stock


def _leg_T(leg, valuation_dt):
    if not leg.is_option() or leg.expiration is None:
        return None
    return time_to_expiry(leg.expiration, valuation_dt)


def leg_value(leg, S, valuation_dt, ctx):
    """Per-share theoretical value of the leg at underlying S and a valuation date."""
    if leg.option_type == "stock":
        return S
    T = _leg_T(leg, valuation_dt)
    if T is None or T <= 0:
        return _intrinsic(leg, S)
    r = ctx.rate_fn(T)
    return bs_price(S, leg.strike, T, r, leg.sigma, leg.option_type, ctx.dividend_yield)


def leg_entry(leg, ctx):
    """Cost basis per share: the supplied entry price, or the current theoretical value."""
    if leg.entry_price is not None:
        return leg.entry_price
    if leg.option_type == "stock":
        return ctx.spot
    return leg_value(leg, ctx.spot, ctx.now, ctx)


def _leg_pnl(leg, S, valuation_dt, ctx, entry):
    return leg.quantity * leg.multiplier * (leg_value(leg, S, valuation_dt, ctx) - entry)


# ----------------------------------------------------------------------
# Position aggregates
# ----------------------------------------------------------------------
def position_greeks(legs, ctx):
    """Net Greeks in engine-native units, scaled by signed quantity * multiplier."""
    net = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    for leg in legs:
        scale = leg.quantity * leg.multiplier
        if leg.option_type == "stock":
            net["delta"] += scale  # stock: delta 1/share, other Greeks 0
            continue
        T = _leg_T(leg, ctx.now)
        if T is None or T <= 0 or not leg.sigma:
            continue
        r = ctx.rate_fn(T)
        g = bs_greeks(ctx.spot, leg.strike, T, r, leg.sigma,
                      leg.option_type, ctx.dividend_yield)
        for key in net:
            net[key] += scale * g[key]
    return net


def net_cost(legs, ctx):
    """Net dollars: positive = debit paid, negative = credit received."""
    return sum(leg.quantity * leg.multiplier * leg_entry(leg, ctx) for leg in legs)


def expiry_pnl(legs, S, ctx, entries=None):
    """Combined P&L at the final expiration, every leg at intrinsic."""
    if entries is None:
        entries = {id(l): leg_entry(l, ctx) for l in legs}
    total = 0.0
    for leg in legs:
        val = S if leg.option_type == "stock" else _intrinsic(leg, S)
        total += leg.quantity * leg.multiplier * (val - entries[id(leg)])
    return total


def _s_max(legs, ctx, factor):
    strikes = [l.strike for l in legs if l.strike]
    return max(strikes + [ctx.spot]) * factor


def payoff_curve(legs, ctx, valuation_dts, s_min=None, s_max=None, points=121):
    """
    Time-aware P&L profile. Returns (xs, {valuation_dt: [y, ...]}), one series per
    date. Option legs not yet expired at a date are repriced via the engine; expired
    legs use intrinsic. The final expiration date reproduces the classic expiry curve.
    """
    strikes = [l.strike for l in legs if l.strike]
    center = ctx.spot
    lo = min([center] + strikes)
    hi = max([center] + strikes)
    pad = 0.4 * center
    if s_min is None:
        s_min = max(0.01, lo - pad)
    if s_max is None:
        s_max = hi + pad
    xs = [s_min + (s_max - s_min) * i / (points - 1) for i in range(points)]
    entries = {id(l): leg_entry(l, ctx) for l in legs}
    curves = {}
    for vdt in valuation_dts:
        curves[vdt] = [
            sum(_leg_pnl(l, S, vdt, ctx, entries[id(l)]) for l in legs)
            for S in xs
        ]
    return xs, curves


def breakevens(legs, ctx, s_max_factor=3.0, samples=800):
    """Underlying prices where the expiry P&L crosses zero, found numerically."""
    entries = {id(l): leg_entry(l, ctx) for l in legs}
    hi = _s_max(legs, ctx, s_max_factor)
    xs = [hi * i / samples for i in range(samples + 1)]
    roots = []
    prev_x = xs[0]
    prev_y = expiry_pnl(legs, prev_x, ctx, entries)
    for x in xs[1:]:
        y = expiry_pnl(legs, x, ctx, entries)
        if prev_y == 0.0:
            roots.append(prev_x)
        elif prev_y * y < 0:
            a, b, fa = prev_x, x, prev_y
            for _ in range(60):
                m = 0.5 * (a + b)
                fm = expiry_pnl(legs, m, ctx, entries)
                if abs(fm) < 1e-9:
                    break
                if fa * fm < 0:
                    b = m
                else:
                    a, fa = m, fm
            roots.append(0.5 * (a + b))
        prev_x, prev_y = x, y
    dedup = []
    for r in roots:
        if not any(abs(r - d) < 1e-4 for d in dedup):
            dedup.append(r)
    return dedup


def max_profit_loss(legs, ctx, s_max_factor=3.0):
    """
    (max_profit, max_loss) in dollars; None means unbounded. The expiry payoff is
    piecewise linear, so finite extrema sit at S=0, at a strike, or at the far end.
    Only the upside (S -> infinity) can be unbounded; the downside is capped at S=0.
    """
    entries = {id(l): leg_entry(l, ctx) for l in legs}
    strikes = sorted({l.strike for l in legs if l.strike})
    hi = _s_max(legs, ctx, s_max_factor)
    cands = sorted({0.0, hi} | set(strikes))
    vals = [expiry_pnl(legs, S, ctx, entries) for S in cands]
    slope_up = sum(
        leg.quantity * leg.multiplier
        * (1.0 if leg.option_type in ("call", "stock") else 0.0)
        for leg in legs
    )
    max_profit = None if slope_up > 1e-9 else max(vals)
    max_loss = None if slope_up < -1e-9 else min(vals)
    return max_profit, max_loss


# ----------------------------------------------------------------------
# Probability of profit (lognormal terminal distribution)
# ----------------------------------------------------------------------
def _final_expiration(legs):
    exps = [l.expiration for l in legs if l.expiration]
    return max(exps) if exps else None


def _atm_sigma(legs, ctx):
    opts = [l for l in legs if l.is_option() and l.sigma]
    if not opts:
        return None
    return min(opts, key=lambda l: abs(l.strike - ctx.spot)).sigma


def _prob_greater(S0, x, T, r, sigma, q):
    """Risk-neutral P(S_T > x) = N(d2)."""
    if x <= 0:
        return 1.0
    if x == float("inf"):
        return 0.0
    return prob_itm(S0, x, T, r, sigma, "call", q)


def prob_of_profit(legs, ctx, sigma=None, expiration=None):
    """
    Risk-neutral probability the position finishes profitable at expiration, under
    the lognormal model, integrating the terminal distribution over the profitable
    regions bounded by the breakevens. Uses a single representative IV (nearest the
    money) for the terminal distribution; the UI states this assumption.
    """
    exp = expiration or _final_expiration(legs)
    if exp is None:
        return None
    T = time_to_expiry(exp, ctx.now)
    if T <= 0:
        return None
    sig = sigma if sigma is not None else _atm_sigma(legs, ctx)
    if not sig:
        return None
    r = ctx.rate_fn(T)
    q = ctx.dividend_yield
    entries = {id(l): leg_entry(l, ctx) for l in legs}
    bounds = [0.0] + sorted(breakevens(legs, ctx)) + [float("inf")]
    pop = 0.0
    for a, b in zip(bounds[:-1], bounds[1:]):
        test = a + 0.1 * ctx.spot + 1.0 if b == float("inf") else 0.5 * (a + b)
        if expiry_pnl(legs, test, ctx, entries) > 0:
            pop += _prob_greater(ctx.spot, a, T, r, sig, q) - _prob_greater(ctx.spot, b, T, r, sig, q)
    return pop


def summarize(legs, ctx):
    """Bundle the position metrics the Strategy page shows."""
    mp, ml = max_profit_loss(legs, ctx)
    return {
        "net_cost": net_cost(legs, ctx),
        "greeks": position_greeks(legs, ctx),
        "breakevens": sorted(breakevens(legs, ctx)),
        "max_profit": mp,
        "max_loss": ml,
        "prob_of_profit": prob_of_profit(legs, ctx),
    }


def leg_breakdown(legs, ctx):
    """
    Per-leg price, signed dollar cost, and signed Greek contributions in display
    units. The cost column sums to the position's net cost and the Greek columns
    sum to the net Greeks, which makes the aggregation explicit. (Breakevens, max
    profit/loss and probability are NOT per-leg sums; they come from the combined
    payoff, so they are not decomposed here.)
    """
    rows = []
    for leg in legs:
        scale = leg.quantity * leg.multiplier
        entry = leg_entry(leg, ctx)
        if leg.option_type == "stock":
            g = {"delta": float(scale), "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
        else:
            T = _leg_T(leg, ctx.now)
            if T and T > 0 and leg.sigma:
                raw = bs_greeks(ctx.spot, leg.strike, T, ctx.rate_fn(T), leg.sigma,
                                leg.option_type, ctx.dividend_yield)
                g = {k: scale * raw[k] for k in ("delta", "gamma", "vega", "theta", "rho")}
            else:
                g = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
        rows.append({
            "option_type": leg.option_type, "quantity": leg.quantity,
            "strike": leg.strike,
            "expiration": leg.expiration.isoformat() if leg.expiration else None,
            "sigma": leg.sigma, "price": entry, "cost": scale * entry,
            "greeks": {  # display units (vega/100, theta/365, rho/100)
                "delta": g["delta"], "gamma": g["gamma"],
                "vega": g["vega"] / 100.0, "theta": g["theta"] / 365.0,
                "rho": g["rho"] / 100.0,
            },
        })
    return rows
