"""
FRED client for the US Treasury constant-maturity par yield curve.

Pulls the dense daily curve (1-month through 30-year) from FRED's keyless CSV
endpoint, one series per request. This is END-OF-DAY data, published once per
business day, so it is the accurate dense source for rho but does not move
intraday (see the rates note in CLAUDE.md). The caller caches it.
"""
import csv
import datetime as dt
import io

import requests

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# FRED constant-maturity series id -> tenor in years.
TREASURY_SERIES = {
    "DGS1MO": 1 / 12,
    "DGS3MO": 0.25,
    "DGS6MO": 0.5,
    "DGS1": 1.0,
    "DGS2": 2.0,
    "DGS3": 3.0,
    "DGS5": 5.0,
    "DGS7": 7.0,
    "DGS10": 10.0,
    "DGS20": 20.0,
    "DGS30": 30.0,
}


class FredError(RuntimeError):
    pass


def _latest_value(csv_text):
    """Return (date_str, value_str) for the last numeric row, or (None, None)."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    last_date, last_val = None, None
    for row in rows[1:]:  # skip header
        if len(row) >= 2 and row[1] not in (".", "", None):
            last_date, last_val = row[0], row[1]
    return last_date, last_val


def get_treasury_curve(min_points=4, lookback_days=45, session=None, timeout=20):
    """
    Fetch the curve from FRED. Returns (curve, as_of_date_str) where curve maps
    tenor-in-years -> rate-as-decimal. Series that fail or lack a recent value are
    skipped; raises FredError if fewer than min_points come back.
    """
    http = session or requests
    cosd = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    curve = {}
    as_of = None
    for series_id, tenor in TREASURY_SERIES.items():
        try:
            resp = http.get(FRED_CSV, params={"id": series_id, "cosd": cosd},
                            timeout=timeout)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        date_str, val = _latest_value(resp.text)
        if val is None:
            continue
        curve[tenor] = float(val) / 100.0
        if as_of is None or (date_str and date_str > as_of):
            as_of = date_str
    if len(curve) < min_points:
        raise FredError(
            f"FRED returned only {len(curve)} usable points (need {min_points})"
        )
    return curve, as_of
