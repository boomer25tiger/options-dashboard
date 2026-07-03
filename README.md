# Options Analysis Dashboard

A locally-run options analysis dashboard for supporting investment decisions.

## Status
- Pricing engine: BUILT and verified (`pricing_engine.py`, tested by `verify_engine.py`).
- Data layer, backend API, React frontend: NOT yet built.

## Read first
`CLAUDE.md` contains the full project context: goals, features, data sources,
data constraints discovered through live testing, architecture, page structure,
and open items. A Claude Code session reads it automatically.

## Verify the engine
```
python3 verify_engine.py
```
Expect all checks to PASS.

## Before real use
Regenerate the Alpaca API key pair in the Alpaca dashboard (the prior pair was
exposed) and store the new secret in a local `.env` file, which is git-ignored.
