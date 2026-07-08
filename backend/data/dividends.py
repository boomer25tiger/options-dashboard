"""
Per-ticker dividend yield with a user override, both displayed and overridable.
Trailing yield is acceptable for indices like SPY and can misstate forward yield
for irregular payers, so both the value and its source are surfaced.
"""
from backend.data.yfinance_client import YFinanceError, get_dividend_yield


def resolve_dividend_yield(ticker, override=None):
    """
    Return (yield_decimal, source). An override wins when given. Otherwise the value
    comes from yfinance; on failure it defaults to 0.0 with source 'fallback'.
    """
    if override is not None:
        return float(override), "override"
    try:
        return get_dividend_yield(ticker), "yfinance"
    except YFinanceError:
        return 0.0, "fallback"
