"""
FastAPI application: thin routes over backend.services.

Acts as the local proxy so the browser never sees the Alpaca keys and has no CORS
issues. During development the React app runs on a separate port and is allowed
through CORS; in the packaged build the backend serves the built frontend from the
same origin (added in the launch phase).
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend import services, strategy
from backend.api.schemas import StrategyLeg, StrategyRequest, VisitRequest
from backend.data.alpaca import AlpacaError
from backend.data.yfinance_client import YFinanceError

app = FastAPI(title="Options Analysis Dashboard API", version="0.1.0")

# Dev origins for the Vite React app. The packaged build is same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _guard(fn, *args, **kwargs):
    """Run a service call, mapping known failures to HTTP status codes."""
    try:
        return fn(*args, **kwargs)
    except services.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except services.DataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except (AlpacaError, YFinanceError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _to_leg(leg: StrategyLeg) -> strategy.Leg:
    multiplier = leg.multiplier
    if multiplier is None:
        multiplier = 1 if leg.option_type == "stock" else 100
    return strategy.Leg(
        option_type=leg.option_type, quantity=leg.quantity, strike=leg.strike,
        expiration=leg.expiration, sigma=leg.sigma, entry_price=leg.entry_price,
        multiplier=multiplier,
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/market-status")
def market_status():
    return services.market_status()


@app.get("/api/assumptions")
def assumptions(ticker: str, dividend_yield: float | None = None):
    return _guard(services.assumptions, ticker, dividend_yield)


@app.get("/api/expirations")
def expirations(ticker: str):
    return _guard(services.expirations, ticker)


@app.get("/api/chain")
def chain(ticker: str,
          num_expirations: int = Query(6, ge=1, le=20),
          iv_source: str = "auto",
          dividend_yield: float | None = None):
    return _guard(services.chain_page, ticker, num_expirations, iv_source,
                  dividend_yield)


@app.get("/api/contract")
def contract(ticker: str, symbol: str, iv_source: str = "auto",
             dividend_yield: float | None = None):
    return _guard(services.contract_detail, ticker, symbol, iv_source,
                  dividend_yield)


@app.get("/api/analysis/realized-vs-implied")
def realized_vs_implied(ticker: str):
    return _guard(services.realized_vs_implied, ticker)


@app.get("/api/analysis/realized-history")
def realized_history(ticker: str, horizon: int = Query(21, ge=5, le=63)):
    return _guard(services.realized_history, ticker, horizon)


@app.get("/api/analysis/surface")
def surface(ticker: str, max_expirations: int = Query(8, ge=2, le=20),
            iv_source: str = "auto"):
    return _guard(services.surface, ticker, max_expirations, iv_source)


@app.get("/api/analysis/smile")
def smile(ticker: str, expiration: str, iv_source: str = "auto"):
    return _guard(services.smile, ticker, expiration, iv_source)


@app.get("/api/analysis/heston")
def heston(ticker: str):
    return _guard(services.heston_calibration, ticker)


@app.get("/api/analysis/hedge")
def hedge(ticker: str,
          lookback: int = Query(30, ge=5, le=120),
          implied_vol: float | None = None,
          option_type: str = "call",
          position: int = Query(1, ge=-1, le=1),
          moneyness: float = Query(1.0, ge=0.7, le=1.3)):
    return _guard(services.hedge_simulation, ticker, lookback, implied_vol,
                  option_type, position, moneyness)


@app.get("/api/analysis/montecarlo")
def montecarlo(ticker: str,
               kind: str = "asian",
               option_type: str = "call",
               days: int = Query(60, ge=5, le=730),
               moneyness: float = Query(1.0, ge=0.7, le=1.3),
               implied_vol: float | None = None,
               average: str = "arithmetic",
               barrier_moneyness: float = Query(1.1, ge=0.5, le=1.5),
               barrier_type: str = "up-and-out"):
    return _guard(services.montecarlo_exotic, ticker, kind, option_type, days,
                  moneyness, implied_vol, average, barrier_moneyness, barrier_type)


@app.get("/api/contract/heston")
def contract_heston(ticker: str, symbol: str):
    return _guard(services.contract_heston, ticker, symbol)


@app.get("/api/contract/montecarlo")
def contract_montecarlo(ticker: str, symbol: str):
    return _guard(services.contract_montecarlo, ticker, symbol)


@app.post("/api/strategy/price")
def strategy_price(req: StrategyRequest):
    legs = [_to_leg(leg) for leg in req.legs]
    if not legs:
        raise HTTPException(status_code=400, detail="no legs supplied")
    return _guard(services.price_strategy, req.ticker, legs, req.iv_source,
                  req.dividend_yield)


@app.post("/api/history/record")
def history_record(req: VisitRequest):
    return _guard(services.record_visit, req.ticker, req.iv_source)


@app.get("/api/history/visits")
def history_visits(ticker: str | None = None,
                   limit: int = Query(200, ge=1, le=2000)):
    return _guard(services.history_visits, ticker, limit)


@app.get("/api/history/tickers")
def history_tickers():
    return _guard(services.history_tickers)


@app.get("/api/history/series")
def history_series(tickers: str, metric: str = "atm_iv"):
    tlist = [t.strip() for t in tickers.split(",") if t.strip()]
    if not tlist:
        raise HTTPException(status_code=400, detail="no tickers supplied")
    return _guard(services.history_series, tlist, metric)


# --- Serve the built React app (same origin) when a production build exists. ---
# Declared after the /api routes so those always take precedence. The catch-all
# returns index.html for unmatched paths so react-router deep links and page
# refreshes resolve client-side. Absent a build (development), this stays off and
# the Vite dev server serves the UI on its own port.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if _DIST.is_dir():
    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (_DIST / full_path).resolve()
        if full_path and candidate.is_file() and _DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
