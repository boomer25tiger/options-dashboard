"""
Alpaca data client: option snapshots, stock bars, and OCC symbol parsing.

Confirmed working against the user's paper account in test_connectivity.py. After
hours the free `indicative` feed still returns Greeks/IV for many contracts,
though frozen at the last session (see CLAUDE.md). Every call raises AlpacaError
with a short, non-sensitive message on failure.
"""
import datetime as dt

import requests

from backend.config import get_alpaca_credentials, get_settings


class AlpacaError(RuntimeError):
    """Raised on a non-200 response or an unexpected payload."""


def _headers(credentials=None):
    cred = credentials or get_alpaca_credentials()
    return {
        "APCA-API-KEY-ID": cred.key_id,
        "APCA-API-SECRET-KEY": cred.secret,
    }


def _as_date_str(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)


def parse_occ_symbol(symbol):
    """
    Parse an OCC option symbol into (underlying, expiration_date, option_type, strike).

    Format: {ROOT}{YYMMDD}{C|P}{STRIKE*1000, zero-padded to 8 digits}.
    Example: SPY260807C00500000 -> ('SPY', date(2026, 8, 7), 'call', 500.0).
    Parsed from the right because the root symbol has a variable length.
    """
    strike = int(symbol[-8:]) / 1000.0
    option_type = "call" if symbol[-9].upper() == "C" else "put"
    yymmdd = symbol[-15:-9]
    expiration = dt.date(2000 + int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))
    underlying = symbol[:-15]
    return underlying, expiration, option_type, strike


def get_option_snapshots(underlying, *, expiration_gte=None, expiration_lte=None,
                         strike_gte=None, strike_lte=None, option_type=None,
                         feed="indicative", limit=100, max_pages=1,
                         credentials=None, settings=None, session=None):
    """
    Fetch option snapshots for an underlying. Returns the `snapshots` dict keyed by
    OCC symbol. Follows pagination up to max_pages to bound the size of the pull.
    """
    settings = settings or get_settings()
    http = session or requests
    url = f"{settings.data_url}/v1beta1/options/snapshots/{underlying}"
    params = {"feed": feed, "limit": limit}
    if expiration_gte:
        params["expiration_date_gte"] = _as_date_str(expiration_gte)
    if expiration_lte:
        params["expiration_date_lte"] = _as_date_str(expiration_lte)
    if strike_gte is not None:
        params["strike_price_gte"] = strike_gte
    if strike_lte is not None:
        params["strike_price_lte"] = strike_lte
    if option_type:
        params["type"] = option_type

    snapshots = {}
    page_token = None
    for _ in range(max_pages):
        if page_token:
            params["page_token"] = page_token
        resp = http.get(url, headers=_headers(credentials), params=params, timeout=30)
        if resp.status_code != 200:
            raise AlpacaError(
                f"snapshots {underlying} -> HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        snapshots.update(data.get("snapshots") or {})
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return snapshots


def get_stock_bars(symbol, *, start, end=None, timeframe="1Day", limit=1000,
                   feed="iex", credentials=None, settings=None, session=None):
    """
    Daily stock bars for realized-vol calculation. Returns a list of bar dicts with
    't' (timestamp) and 'c' (close), oldest first. Free tier serves the IEX feed.
    """
    settings = settings or get_settings()
    http = session or requests
    url = f"{settings.data_url}/v2/stocks/{symbol}/bars"
    params = {
        "timeframe": timeframe,
        "start": _as_date_str(start),
        "limit": limit,
        "adjustment": "split",
        "feed": feed,
    }
    if end:
        params["end"] = _as_date_str(end)

    bars = []
    page_token = None
    while True:
        if page_token:
            params["page_token"] = page_token
        resp = http.get(url, headers=_headers(credentials), params=params, timeout=30)
        if resp.status_code != 200:
            raise AlpacaError(
                f"bars {symbol} -> HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        bars.extend(data.get("bars") or [])
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return bars
