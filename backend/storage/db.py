"""
SQLite storage for examined-stock history (CLAUDE.md feature 10).

Records KEY METRICS PER VISIT (spot, ATM IV, realized-vol windows, the rank proxy,
timestamp), not the full chain. Capturing the ATM IV per visit also seeds the real
IV series over time, which becomes true IV rank once enough visits accumulate (F6).

The database file is git-ignored (*.db). Its path is the project-root history.db by
default, overridable with the HISTORY_DB_PATH environment variable so tests can use
a throwaway file. Each call opens and closes its own connection, which keeps it safe
under FastAPI's threadpool.
"""
import datetime as dt
import os
import sqlite3
from contextlib import closing

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "history.db")

# Numeric metric columns recorded per visit. Also the whitelist of series metrics.
METRIC_COLUMNS = [
    "spot", "atm_iv", "rv_10", "rv_20", "rv_30", "rv_60",
    "iv_rank", "iv_percentile",
]
METRICS = set(METRIC_COLUMNS)


def _db_path(path=None):
    return path or os.environ.get("HISTORY_DB_PATH") or DEFAULT_DB_PATH


def _connect(path=None):
    conn = sqlite3.connect(_db_path(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path=None):
    with closing(_connect(path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                spot REAL, atm_iv REAL,
                rv_10 REAL, rv_20 REAL, rv_30 REAL, rv_60 REAL,
                iv_rank REAL, iv_percentile REAL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_visits_ticker_ts "
            "ON visits(ticker, timestamp)"
        )
        conn.commit()


def record_visit(ticker, metrics, timestamp, path=None):
    """Insert one visit row and return it as a dict."""
    init_db(path)
    columns = ["ticker", "timestamp"] + METRIC_COLUMNS
    values = [ticker.upper(), timestamp] + [metrics.get(c) for c in METRIC_COLUMNS]
    placeholders = ",".join("?" * len(columns))
    with closing(_connect(path)) as conn:
        cur = conn.execute(
            f"INSERT INTO visits ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM visits WHERE id = ?",
                           (cur.lastrowid,)).fetchone()
    return dict(row)


def list_visits(ticker=None, limit=200, path=None):
    """Visits, most recent first, optionally filtered to one ticker."""
    init_db(path)
    with closing(_connect(path)) as conn:
        if ticker:
            rows = conn.execute(
                "SELECT * FROM visits WHERE ticker = ? "
                "ORDER BY timestamp DESC, id DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM visits ORDER BY timestamp DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def distinct_tickers(path=None):
    init_db(path)
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM visits ORDER BY ticker"
        ).fetchall()
    return [r["ticker"] for r in rows]


def metric_series(tickers, metric, path=None):
    """
    Time series of one metric per ticker, oldest first, skipping null values.
    The metric name is validated against the whitelist before interpolation, so
    the column name cannot inject SQL.
    """
    if metric not in METRICS:
        raise ValueError(f"unknown metric '{metric}'; choose from {sorted(METRICS)}")
    init_db(path)
    out = {}
    with closing(_connect(path)) as conn:
        for ticker in tickers:
            rows = conn.execute(
                f"SELECT timestamp, {metric} AS value FROM visits "
                f"WHERE ticker = ? AND {metric} IS NOT NULL ORDER BY timestamp",
                (ticker.upper(),),
            ).fetchall()
            out[ticker.upper()] = [
                {"timestamp": r["timestamp"], "value": r["value"]} for r in rows
            ]
    return out
