"""
FastAPI application: thin routes over backend.services.

Acts as the local proxy so the browser never sees the Alpaca keys and has no CORS
issues. During development the React app runs on a separate port and is allowed
through CORS; in the packaged build the backend serves the built frontend from the
same origin (added in the launch phase).
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend import services, strategy
from backend.api.schemas import StrategyLeg, StrategyRequest
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


@app.get("/api/analysis/surface")
def surface(ticker: str, max_expirations: int = Query(8, ge=2, le=20),
            iv_source: str = "auto"):
    return _guard(services.surface, ticker, max_expirations, iv_source)


@app.get("/api/analysis/smile")
def smile(ticker: str, expiration: str, iv_source: str = "auto"):
    return _guard(services.smile, ticker, expiration, iv_source)


@app.post("/api/strategy/price")
def strategy_price(req: StrategyRequest):
    legs = [_to_leg(leg) for leg in req.legs]
    if not legs:
        raise HTTPException(status_code=400, detail="no legs supplied")
    return _guard(services.price_strategy, req.ticker, legs, req.iv_source,
                  req.dividend_yield)
