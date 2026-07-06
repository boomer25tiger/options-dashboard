"""
Phase 4 verification: SQLite history storage and the History API routes.

Uses a throwaway database (HISTORY_DB_PATH set to a temp file before any backend
import), so the real history.db is never touched. Storage logic is checked with
synthetic rows (no network); the API routes are then checked end to end, including
one live visit recorded for SPY.

Run:  python3 check_storage.py
"""
import os
import sys
import tempfile

# Point the storage layer at a throwaway file BEFORE importing backend modules.
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["HISTORY_DB_PATH"] = _TMP.name

from fastapi.testclient import TestClient  # noqa: E402
from backend.api.main import app  # noqa: E402
from backend.storage import db  # noqa: E402

client = TestClient(app)
_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def main():
    try:
        # -- storage unit tests (synthetic, no network) -----------------
        hr("STORAGE LAYER (synthetic rows)")
        db.record_visit("testa", {"spot": 100.0, "atm_iv": 0.20, "rv_20": 0.18,
                                  "iv_rank": 40.0, "iv_percentile": 55.0},
                        "2026-06-01T12:00:00+00:00")
        db.record_visit("testa", {"spot": 102.0, "atm_iv": 0.22, "rv_20": 0.19,
                                  "iv_rank": 48.0, "iv_percentile": 60.0},
                        "2026-06-02T12:00:00+00:00")
        db.record_visit("testb", {"spot": 50.0, "atm_iv": 0.35, "rv_20": 0.30,
                                  "iv_rank": 70.0, "iv_percentile": 80.0},
                        "2026-06-01T12:00:00+00:00")

        rows = db.list_visits("TESTA")
        check("record + list per ticker", len(rows) == 2, f"{len(rows)} rows")
        check("list is newest-first",
              rows[0]["timestamp"] > rows[1]["timestamp"])
        check("stored metric round-trips", rows[0]["atm_iv"] == 0.22,
              f"atm_iv={rows[0]['atm_iv']}")

        tickers = db.distinct_tickers()
        check("distinct tickers", set(tickers) == {"TESTA", "TESTB"}, str(tickers))

        series = db.metric_series(["TESTA", "TESTB"], "atm_iv")
        check("metric series per ticker, oldest-first",
              len(series["TESTA"]) == 2
              and series["TESTA"][0]["value"] == 0.20
              and series["TESTA"][1]["value"] == 0.22,
              f"TESTA={[p['value'] for p in series['TESTA']]}")
        check("cross-ticker series returns both",
              "TESTA" in series and "TESTB" in series)

        bad_metric = False
        try:
            db.metric_series(["TESTA"], "not_a_metric")
        except ValueError:
            bad_metric = True
        check("unknown metric rejected", bad_metric)

        # persistence across a fresh connection (each call reconnects)
        check("persists across connections", len(db.list_visits("TESTB")) == 1)

        # -- API routes -------------------------------------------------
        hr("HISTORY API (synthetic rows already stored)")
        r = client.get("/api/history/visits", params={"ticker": "TESTA"})
        check("GET /history/visits 200", r.status_code == 200
              and len(r.json()["visits"]) == 2)
        r = client.get("/api/history/tickers")
        check("GET /history/tickers includes both",
              set(r.json()["tickers"]) >= {"TESTA", "TESTB"})
        r = client.get("/api/history/series",
                       params={"tickers": "TESTA,TESTB", "metric": "iv_rank"})
        check("GET /history/series 200 for two tickers",
              r.status_code == 200 and len(r.json()["series"]) == 2)
        r = client.get("/api/history/series",
                       params={"tickers": "TESTA", "metric": "bogus"})
        check("GET /history/series bad metric -> 400", r.status_code == 400,
              f"status={r.status_code}")

        # -- live visit recording for SPY -------------------------------
        hr("LIVE VISIT RECORD (SPY)")
        r = client.post("/api/history/record", json={"ticker": "SPY"})
        check("POST /history/record 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            visit = r.json()
            check("recorded visit has spot",
                  isinstance(visit.get("spot"), (int, float)),
                  f"spot={visit.get('spot')}")
            check("recorded visit has ATM IV (seeds real IV series)",
                  visit.get("atm_iv") is not None, f"atm_iv={visit.get('atm_iv')}")
            check("recorded visit has realized vol + rank",
                  visit.get("rv_20") is not None and visit.get("iv_rank") is not None,
                  f"rv_20={visit.get('rv_20')} iv_rank={visit.get('iv_rank')}")
            r2 = client.get("/api/history/visits", params={"ticker": "SPY"})
            check("SPY visit reads back", len(r2.json()["visits"]) >= 1)
            r3 = client.get("/api/history/series",
                            params={"tickers": "SPY", "metric": "atm_iv"})
            check("SPY atm_iv series has a point",
                  len(r3.json()["series"].get("SPY", [])) >= 1)

        # -- summary ----------------------------------------------------
        hr("SUMMARY")
        print(f"  {len(_PASSES)} passed, {len(_FAILS)} failed")
        if _FAILS:
            print("  FAILED: " + ", ".join(_FAILS))
        sys.exit(0 if not _FAILS else 1)
    finally:
        os.unlink(_TMP.name)


if __name__ == "__main__":
    main()
