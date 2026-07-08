"""
Exercise every API route in-process with the FastAPI TestClient (no separate
server). The service layer makes real calls to Alpaca / yfinance / FRED, so this
checks the API end to end against live SPY data.

Run:  python3 check_api.py
"""
import sys

from fastapi.testclient import TestClient

from backend.api.main import app

TICKER = "SPY"
client = TestClient(app)
_PASSES, _FAILS = [], []


def check(label, ok, detail=""):
    (_PASSES if ok else _FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def main():
    hr("HEALTH + MARKET STATUS")
    r = client.get("/api/health")
    check("health 200 + ok", r.status_code == 200 and r.json().get("status") == "ok")
    r = client.get("/api/market-status")
    check("market-status 200", r.status_code == 200, f"is_open={r.json().get('is_open')}")

    hr("ASSUMPTIONS")
    r = client.get("/api/assumptions", params={"ticker": TICKER})
    j = r.json()
    check("assumptions 200", r.status_code == 200)
    check("rate source is fred", j.get("rate", {}).get("source") == "fred",
          f"source={j.get('rate',{}).get('source')}")
    check("dividend yield sane", 0 <= j.get("dividend", {}).get("value", -1) < 0.05,
          f"q={j.get('dividend',{}).get('value')}")

    hr("EXPIRATIONS")
    r = client.get("/api/expirations", params={"ticker": TICKER})
    exps = r.json().get("expirations", [])
    check("expirations returned", r.status_code == 200 and len(exps) > 0,
          f"{len(exps)} expirations")
    first_exp = exps[0] if exps else None

    hr("CHAIN")
    r = client.get("/api/chain", params={"ticker": TICKER, "num_expirations": 3})
    j = r.json()
    contracts = j.get("contracts", [])
    with_greeks = [c for c in contracts if c["greeks"]["delta"] is not None]
    check("chain 200 + contracts", r.status_code == 200 and len(contracts) > 0,
          f"{len(contracts)} contracts")
    check("spot present", isinstance(j.get("spot"), (int, float)))
    check("most contracts have Greeks", len(with_greeks) >= 0.5 * len(contracts),
          f"{len(with_greeks)}/{len(contracts)}")
    check("iv_rank proxy present", j.get("iv_rank") is not None
          and "rank" in (j.get("iv_rank") or {}))
    sample = next((c for c in with_greeks), None)
    if sample:
        v = sample["greeks"]["vega"]
        check("vega in display units (per 1% vol)", v is None or abs(v) < 5,
              f"vega={round(v,4) if v is not None else None}")
        symbol = sample["symbol"]
    else:
        symbol = None

    hr("CONTRACT DETAIL")
    if symbol:
        r = client.get("/api/contract", params={"ticker": TICKER, "symbol": symbol})
        j = r.json()
        check("contract 200", r.status_code == 200, symbol)
        bs = j.get("pricing", {}).get("black_scholes")
        binom = j.get("pricing", {}).get("binomial_american")
        eep = j.get("pricing", {}).get("early_exercise_premium")
        check("BS and binomial prices present",
              isinstance(bs, (int, float)) and isinstance(binom, (int, float)),
              f"BS={round(bs,4) if bs else None} binom={round(binom,4) if binom else None}")
        check("early-exercise premium >= -0.01 (American >= European)",
              eep is None or eep >= -0.01, f"eep={round(eep,4) if eep is not None else None}")
        prob = j.get("probability", {})
        check("prob_itm in [0,1]", prob.get("prob_itm") is None
              or 0 <= prob["prob_itm"] <= 1)
    else:
        check("contract detail (skipped, no sample symbol)", False)

    hr("ANALYSIS: REALIZED VS IMPLIED")
    r = client.get("/api/analysis/realized-vs-implied", params={"ticker": TICKER})
    j = r.json()
    rv = j.get("realized_vol", {})
    check("realized vs implied 200", r.status_code == 200)
    check("realized vol windows present", all(k in rv for k in ("10", "20", "30", "60")),
          f"keys={list(rv.keys())}")
    check("atm_iv present", j.get("atm_iv") is not None, f"atm_iv={j.get('atm_iv')}")

    hr("ANALYSIS: SURFACE")
    r = client.get("/api/analysis/surface", params={"ticker": TICKER, "max_expirations": 4})
    j = r.json()
    pts = j.get("points", [])
    check("surface 200 + points", r.status_code == 200 and len(pts) > 0,
          f"{len(pts)} points across {len(j.get('expirations', []))} expirations")
    check("surface points well-formed",
          all({"strike", "tenor", "iv"} <= set(p) for p in pts[:5]))

    hr("ANALYSIS: SMILE")
    if first_exp:
        r = client.get("/api/analysis/smile",
                       params={"ticker": TICKER, "expiration": first_exp})
        j = r.json()
        check("smile 200 + points", r.status_code == 200 and len(j.get("points", [])) > 0,
              f"{len(j.get('points', []))} points at {first_exp}")

    hr("STRATEGY PRICING")
    if first_exp:
        # Fetch chain to pick two real strikes around spot.
        chain = client.get("/api/chain",
                           params={"ticker": TICKER, "num_expirations": 1}).json()
        spot = chain["spot"]
        calls = sorted(
            (c for c in chain["contracts"]
             if c["type"] == "call" and c["expiration"] == first_exp and c["iv"]),
            key=lambda c: c["strike"],
        )
        lower = min(calls, key=lambda c: abs(c["strike"] - spot))
        higher = next((c for c in calls if c["strike"] > lower["strike"] + 1), None)
        if higher:
            body = {
                "ticker": TICKER,
                "legs": [
                    {"option_type": "call", "quantity": 1, "strike": lower["strike"],
                     "expiration": first_exp},
                    {"option_type": "call", "quantity": -1, "strike": higher["strike"],
                     "expiration": first_exp},
                ],
            }
            r = client.post("/api/strategy/price", json=body)
            j = r.json()
            check("strategy 200", r.status_code == 200, str(r.status_code))
            summ = j.get("summary", {})
            check("bull call spread max profit and loss bounded",
                  summ.get("max_profit") is not None and summ.get("max_loss") is not None,
                  f"mp={summ.get('max_profit')} ml={summ.get('max_loss')}")
            check("has breakeven(s)", len(summ.get("breakevens", [])) >= 1,
                  f"breakevens={[round(b,2) for b in summ.get('breakevens', [])]}")
            check("payoff curves include now and expiry",
                  "now" in j.get("payoff", {}).get("curves", {})
                  and "expiry" in j.get("payoff", {}).get("curves", {}),
                  f"curves={list(j.get('payoff', {}).get('curves', {}).keys())}")
        else:
            check("strategy pricing (no second strike found)", False)

    hr("SUMMARY")
    print(f"  {len(_PASSES)} passed, {len(_FAILS)} failed")
    if _FAILS:
        print("  FAILED: " + ", ".join(_FAILS))
    sys.exit(0 if not _FAILS else 1)


if __name__ == "__main__":
    main()
