# Options Desk

A locally-run options analysis dashboard, built for making real decisions under
time pressure. It pulls a live options chain, prices every contract four ways,
fits and stress-tests the volatility surface, simulates strategies and hedges, and
reads each result back in plain language. Everything runs on your own machine.
Nothing is hosted, and no account beyond a free market-data key is needed.

The emphasis is accuracy, legibility of dense numbers, and fast scanning. The math
core is pure Python, verified against textbook and analytic benchmarks, and the
interface is a multi-page React app with genuinely interactive 3D and 2D charts.

---

## Screenshots

**Contract pricing, four methods side by side, with Monte Carlo converging on the
closed form.**

![Contract pricing models](docs/screenshots/contract.png)

**Monte Carlo of a barrier option: the price is the discounted average payoff over
every simulated path, and the red paths that touch the barrier are what knock the
price below the vanilla.**

![Monte Carlo path cloud](docs/screenshots/montecarlo.png)

**Live options chain with per-strike Greeks and IV.**

![Options chain](docs/screenshots/chain.png)

**Volatility surface with an SVI-fitted overlay and the raw market points.**

![Volatility surface](docs/screenshots/surface.png)

**Delta-hedging simulation over a real historical path, split into its gamma and
theta halves.**

![Delta hedging](docs/screenshots/hedging.png)

**Multi-leg strategy builder with a time-aware payoff diagram.**

![Strategy builder](docs/screenshots/strategy.png)

---

## Quick start

Prerequisites: Python 3.11 or newer, and Node.js 18 or newer.

1. Copy `.env.example` to `.env` and add your Alpaca paper-trading keys (free from
   the Alpaca dashboard). yfinance and the FRED rate curve need no key.
2. Start it:

   ```
   ./run.sh
   ```

   On a Mac you can also double-click **Start Options Dashboard.command** in Finder.

The script creates a local Python environment, installs everything on first run,
builds the web app, and opens your browser to `http://localhost:8000`. The Python
backend serves both the API and the built interface from that one address, so there
is nothing else to start.

---

## What it does

Five pages, each with its own tabs, sharing a persistent top bar for the active
ticker, the IV source, market status, and the pricing assumptions.

- **Chain.** The live options chain per expiration: bid, ask, volume, open interest,
  IV, and Greeks per strike, with an IV-rank readout. The entry point for the rest.
- **Analysis.** Five tabs on the selected underlying.
  - *Volatility Surface.* A 3D IV surface with an optional SVI-fitted overlay and a
    Heston-calibrated overlay, arbitrage-violation flags with a written report,
    and a linked ATM term-structure curve.
  - *Volatility Smile.* A 2D IV slice for one expiration with the 25-delta skew and
    butterfly.
  - *Realized vs Implied.* Realized vol (Garman-Klass and close-to-close), the
    volatility risk premium, and a one-year vol cone.
  - *Delta Hedging.* A simulation of hedging one option over a real historical path,
    with the running P&L split into its gamma gain and theta bleed.
  - *Monte Carlo.* A builder for path-dependent Asian and barrier options, showing
    the cloud of simulated underlying paths behind the price.
- **Strategy.** A freeform and preset multi-leg builder with a time-aware payoff
  diagram, aggregate Greeks, breakevens, max profit and loss, and probability of
  profit.
- **Contract.** A single option priced four ways side by side, with a probability
  and breakeven view.
- **History.** Key metrics per visit stored locally, charted over time, comparable
  across tickers.

Throughout, a short directional **read** turns the numbers into an interpretation,
tied to a specific value, with its assumption stated and no explicit buy or sell.

---

## The modeling

The pricing math is a pure-Python core, independent of the data layer and verified
on its own before anything is built on it.

- **Black-Scholes and binomial.** Closed-form European pricing and a Cox-Ross-
  Rubinstein tree for American early exercise, with analytical Greeks. Verified
  against Hull's textbook values and put-call parity to machine precision
  (`pricing_engine.py`, `verify_engine.py`).
- **Heston stochastic volatility.** A characteristic-function pricer using the
  numerically stable little-trap formulation, with calibration to the live chain by
  minimizing pricing error across strikes and maturities. Verified against an
  independent Monte Carlo and the Black-Scholes limit (`heston.py`,
  `backend/heston_calib.py`).
- **Monte Carlo.** Simulation pricing with antithetic variates and a confidence
  interval, for vanilla convergence and for path-dependent Asian and barrier
  options. Verified against the geometric-Asian closed form and barrier in-out
  parity (`backend/montecarlo.py`).
- **Delta-hedging simulation.** A self-financing hedge over a historical path that
  converts the implied-versus-realized vol spread into P&L (`backend/hedging.py`).
- **Vectorized engine.** A NumPy port that prices a whole chain in one array
  operation, reproducing the scalar engine element for element and benchmarked at
  roughly 5x on the Greeks (`engine_vec.py`, `benchmark_vec.py`).

Risk-free rates are matched to each option's expiry by interpolating the FRED
Treasury constant-maturity curve, which matters for the longer-dated contracts.
Dividend yield is pulled per ticker and is user-overridable.

---

## Architecture

- **Backend.** Python with FastAPI. A data layer over Alpaca (live chain, quotes,
  stock bars), yfinance (fallback IV, dividends), and FRED (rate curve), plus the
  pricing engine and the analytics. It serves a JSON API and, in the packaged
  build, the web app itself.
- **Frontend.** React with Vite and TypeScript, Zustand for shared state, TanStack
  Query for data, and Plotly for the 3D surface and the interactive charts.
- **Storage.** A local SQLite file for the examined-stock history.

Data sources were chosen for after-hours coverage. Alpaca serves after-hours IV and
Greeks through its free indicative feed with partial coverage, and yfinance fills
the rest, so the surface and Greeks stay populated when the market is closed.

---

## Verification

The math is checked by a set of scripts, each pinning a component to values it must
reproduce rather than to a golden output:

```
python3 verify_engine.py         # Black-Scholes / binomial vs textbook
python3 verify_engine_vec.py     # vectorized engine vs the scalar engine
python3 verify_heston.py         # Heston vs Monte Carlo and the BS limit
python3 check_heston_calib.py    # calibration recovers known parameters
python3 check_hedging.py         # hedge P&L economics
python3 check_montecarlo.py      # convergence, geometric Asian, barrier parity
python3 check_commentary.py      # the directional reads
python3 check_api.py             # the API endpoints
```

---

## Security

Keep your Alpaca keys in `.env`, which is git-ignored, and never commit them. The
paper keys used during development were rotated. Options data needs only read access
to the chain and quotes.

---

## License

MIT. See [LICENSE](LICENSE).
