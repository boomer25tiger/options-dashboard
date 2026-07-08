"""
yfinance client: option chains with IV, spot, dividend yield, and Treasury rates.

yfinance is an unofficial scraper and can break when Yahoo changes its site. Every
call is wrapped so a failure raises YFinanceError with a clear message rather than
surfacing a raw exception to the caller.
"""
from typing import Any, Dict, List, Optional, Tuple

import yfinance as yf


class YFinanceError(RuntimeError):
    pass


# Treasury yield tickers (Yahoo quotes these in percent) and their tenor in years.
TREASURY_TICKERS = {
    "^IRX": 0.25,   # 13-week T-bill
    "^FVX": 5.0,    # 5-year note
    "^TNX": 10.0,   # 10-year note
    "^TYX": 30.0,   # 30-year bond
}


def get_expirations(ticker: str) -> List[str]:
    try:
        exps = yf.Ticker(ticker).options
    except Exception as exc:
        raise YFinanceError(f"expirations for {ticker} failed: {exc}") from exc
    return list(exps or [])


def get_option_chain(ticker: str, expiration: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (calls_records, puts_records) as lists of dicts for one expiration."""
    try:
        chain = yf.Ticker(ticker).option_chain(expiration)
    except Exception as exc:
        raise YFinanceError(
            f"option_chain({ticker}, {expiration}) failed: {exc}"
        ) from exc
    return chain.calls.to_dict("records"), chain.puts.to_dict("records")


def get_spot(ticker: str) -> Optional[float]:
    """Last price for the underlying. Tries fast_info, then recent daily history."""
    t = yf.Ticker(ticker)
    try:
        fi = t.fast_info
        for attr in ("last_price", "lastPrice"):
            price = getattr(fi, attr, None)
            if price:
                return float(price)
        try:
            price = fi["lastPrice"]
            if price:
                return float(price)
        except Exception:
            pass
    except Exception:
        pass
    try:
        hist = t.history(period="5d")
        if len(hist):
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        raise YFinanceError(f"spot for {ticker} failed: {exc}") from exc
    return None


def get_dividend_yield(ticker: str) -> float:
    """
    Trailing dividend yield as a decimal (0.0076 = 0.76%), or 0.0 if none is reported.

    yfinance's `dividendYield` is unit-inconsistent across versions (it currently
    quotes a percent, e.g. 0.98 for 0.98%), and magnitude alone cannot disambiguate
    a percent from a fraction near 1. So the reliable fields are preferred in order:
    the trailing yield fraction, then the dollar rate over price (unit-unambiguous),
    then the fund 'yield' fraction, and only last the ambiguous `dividendYield`.
    """
    try:
        info = yf.Ticker(ticker).info
    except Exception as exc:
        raise YFinanceError(f"info for {ticker} failed: {exc}") from exc

    def _sane_fraction(v: Any) -> bool:
        return v is not None and 0.0 <= float(v) < 0.5

    # 1. Trailing yield field is a clean fraction across yfinance versions.
    v = info.get("trailingAnnualDividendYield")
    if _sane_fraction(v):
        return float(v)

    # 2. Dollar dividend rate divided by price is unit-unambiguous.
    rate = info.get("trailingAnnualDividendRate") or info.get("dividendRate")
    price = (info.get("regularMarketPrice") or info.get("previousClose")
             or info.get("currentPrice"))
    if rate and price:
        y = float(rate) / float(price)
        if 0.0 <= y < 0.5:
            return y

    # 3. 'yield' is a fraction when present (common for funds/ETFs).
    v = info.get("yield")
    if _sane_fraction(v):
        return float(v)

    # 4. Last resort: dividendYield, which modern yfinance quotes in percent.
    v = info.get("dividendYield")
    if v is not None:
        v = float(v)
        return v / 100.0 if v > 0.5 else v

    return 0.0


def get_treasury_rates() -> Dict[float, float]:
    """
    Return {tenor_in_years: rate_as_decimal} from the Treasury yield indices.
    Yahoo quotes them in percent, so each is divided by 100. Tickers that fail are
    skipped; the caller handles an incomplete curve. Raises if none succeed.
    """
    rates = {}
    for symbol, tenor in TREASURY_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist):
                rates[tenor] = float(hist["Close"].iloc[-1]) / 100.0
        except Exception:
            continue
    if not rates:
        raise YFinanceError("no Treasury rates could be fetched")
    return rates
