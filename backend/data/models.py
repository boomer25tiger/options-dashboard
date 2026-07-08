"""
Normalized data structures shared across the data layer and the API.

Greeks are stored in engine-native units: vega per 1.00 change in vol, theta per
year, rho per 1.00 change in rate. Display conversions (per 1% point, per day)
happen at the presentation layer, so the raw numbers have one source of truth.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


@dataclass
class Greeks:
    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None
    rho: Optional[float] = None


@dataclass
class OptionContract:
    symbol: str
    underlying: str
    option_type: str                       # 'call' or 'put'
    strike: float
    expiration: date
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    iv: Optional[float] = None
    iv_source: Optional[str] = None        # 'alpaca' | 'yfinance' | 'computed' | 'parity'
    greeks: Greeks = field(default_factory=Greeks)
    greeks_source: Optional[str] = None    # 'recomputed'
    time_to_expiry: Optional[float] = None  # years
    rate_used: Optional[float] = None
    quote_timestamp: Optional[str] = None
    in_the_money: Optional[bool] = None


@dataclass
class OptionChain:
    underlying: str
    spot: Optional[float]
    as_of: datetime
    dividend_yield: Optional[float] = None
    dividend_source: Optional[str] = None
    expirations: List[date] = field(default_factory=list)
    contracts: List[OptionContract] = field(default_factory=list)
