"""
Connectivity / data-availability test for the options dashboard.

Checks two independent data paths from THIS machine, without building anything:

  1. Alpaca options-chain SNAPSHOT for SPY, authenticated with the .env keys.
  2. yfinance option-chain for SPY, including implied volatility.

For each, it reports what came back and whether Greeks and IV are present. When the
market is closed the Alpaca snapshot may carry a latestQuote with no Greeks or IV,
while yfinance still supplies IV. This script confirms or refutes that.

Secrets are never printed. The key ID is masked; the secret is never shown.
Run:  python3 test_connectivity.py
"""

import os
import sys
import json
from datetime import datetime, timezone

import requests


# Load .env (no python-dotenv dependency; parse KEY=VALUE lines ourselves)
def load_env(path=".env"):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def mask(value):
    """Show only enough to confirm the right value loaded, never the whole thing."""
    if not value:
        return "<empty>"
    if len(value) <= 6:
        return value[0] + "***"
    return value[:4] + "..." + value[-2:]


def hr(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def test_alpaca(env):
    hr("TEST 1 — ALPACA OPTIONS SNAPSHOT (SPY)")

    key_id = env.get("APCA_API_KEY_ID")
    secret = env.get("APCA_API_SECRET_KEY")
    data_host = env.get("APCA_API_DATA_URL", "https://data.alpaca.markets")

    if not key_id or not secret:
        print("[FAIL] APCA_API_KEY_ID / APCA_API_SECRET_KEY not found in .env")
        return False

    print(f"Key ID loaded:   {mask(key_id)}")
    print("Secret loaded:   <present, not shown>")
    print(f"Data host:       {data_host}")

    url = f"{data_host}/v1beta1/options/snapshots/SPY"
    headers = {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret,
    }
    # Keep the pull small; a full chain is thousands of contracts.
    params = {"limit": 100, "feed": "indicative"}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        print(f"[FAIL] Network error reaching Alpaca: {exc}")
        return False

    print(f"HTTP status:     {resp.status_code}")

    if resp.status_code != 200:
        # Show a short, non-sensitive snippet to diagnose auth/permission issues.
        snippet = resp.text[:400].replace(key_id, mask(key_id))
        print(f"[FAIL] Non-200 response. Body (truncated):\n{snippet}")
        return False

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print("[FAIL] Response was not valid JSON.")
        return False

    snapshots = data.get("snapshots", {})
    total = len(snapshots)
    print(f"Contracts returned: {total}")

    if total == 0:
        print("[WARN] 200 OK but zero contracts. Endpoint reachable, no data returned.")
        return True

    # Tally what fields are present across the returned contracts.
    with_quote = sum(1 for s in snapshots.values() if s.get("latestQuote"))
    with_trade = sum(1 for s in snapshots.values() if s.get("latestTrade"))
    with_greeks = sum(1 for s in snapshots.values() if s.get("greeks"))
    with_iv = sum(
        1 for s in snapshots.values()
        if s.get("impliedVolatility") is not None
    )

    print(f"  with latestQuote:      {with_quote}/{total}")
    print(f"  with latestTrade:      {with_trade}/{total}")
    print(f"  with greeks:           {with_greeks}/{total}")
    print(f"  with impliedVolatility:{with_iv}/{total}")

    # Show one sample contract so we can see the actual shape.
    sample_sym = next(iter(snapshots))
    sample = snapshots[sample_sym]
    print(f"\nSample contract: {sample_sym}")
    print(f"  top-level keys: {sorted(sample.keys())}")
    q = sample.get("latestQuote")
    if q:
        print(
            "  latestQuote: "
            f"bid={q.get('bp')} (size {q.get('bs')}), "
            f"ask={q.get('ap')} (size {q.get('as')}), "
            f"t={q.get('t')}"
        )
    if sample.get("greeks"):
        print(f"  greeks: {sample['greeks']}")
    else:
        print("  greeks: ABSENT")
    print(f"  impliedVolatility: {sample.get('impliedVolatility', 'ABSENT')}")

    print("\nSummary:")
    print(f"  Chain snapshot reachable and authenticated: YES")
    print(f"  Greeks present now (market closed):         "
          f"{'YES' if with_greeks else 'NO'}")
    print(f"  IV present now (market closed):             "
          f"{'YES' if with_iv else 'NO'}")
    return True


def test_yfinance():
    hr("TEST 2 — YFINANCE OPTION CHAIN (SPY)")

    try:
        import yfinance as yf
    except ImportError:
        print("[FAIL] yfinance not installed.")
        return False

    try:
        ticker = yf.Ticker("SPY")
        expirations = ticker.options
    except Exception as exc:
        print(f"[FAIL] yfinance could not fetch expirations: {exc}")
        return False

    if not expirations:
        print("[FAIL] yfinance returned no expirations (Yahoo may have changed / blocked).")
        return False

    print(f"Expirations available: {len(expirations)}")
    print(f"  first few: {list(expirations[:6])}")

    exp = expirations[0]
    try:
        chain = ticker.option_chain(exp)
    except Exception as exc:
        print(f"[FAIL] yfinance could not fetch option_chain({exp}): {exc}")
        return False

    calls = chain.calls
    puts = chain.puts
    print(f"\nNearest expiration tested: {exp}")
    print(f"  calls rows: {len(calls)}   puts rows: {len(puts)}")

    if "impliedVolatility" not in calls.columns:
        print("[FAIL] No 'impliedVolatility' column in calls.")
        return False

    iv = calls["impliedVolatility"]
    non_null = int(iv.notna().sum())
    non_zero = int((iv.fillna(0) > 0).sum())
    print(f"  calls impliedVolatility: {non_null}/{len(calls)} non-null, "
          f"{non_zero} greater than zero")

    # Show a mid-chain sample row (near the money is roughly the middle).
    if len(calls):
        mid = len(calls) // 2
        row = calls.iloc[mid]
        print("\nSample call row (near mid-chain):")
        print(f"  contract:  {row.get('contractSymbol')}")
        print(f"  strike:    {row.get('strike')}")
        print(f"  bid/ask:   {row.get('bid')} / {row.get('ask')}")
        print(f"  lastPrice: {row.get('lastPrice')}")
        print(f"  volume:    {row.get('volume')}   OI: {row.get('openInterest')}")
        print(f"  IV:        {row.get('impliedVolatility')}")
        print(f"  inTheMoney:{row.get('inTheMoney')}")

    print(f"\n  columns available: {list(calls.columns)}")
    print("\nSummary:")
    print(f"  Option chain reachable:                 YES")
    print(f"  IV present now (market closed):         "
          f"{'YES' if non_zero else 'NO'}")
    print(f"  Greeks from yfinance:                   NO (never provided; compute via engine)")
    return True


def main():
    now_utc = datetime.now(timezone.utc)
    print("Connectivity test run at (UTC):", now_utc.isoformat(timespec="seconds"))
    print("Local date:", now_utc.astimezone().strftime("%Y-%m-%d %H:%M %Z"))
    print("Note: market is closed today (holiday); this is an after-hours test.")

    env = load_env()
    alpaca_ok = test_alpaca(env)
    yf_ok = test_yfinance()

    hr("OVERALL")
    print(f"Alpaca snapshot reachable/authenticated: {'YES' if alpaca_ok else 'NO'}")
    print(f"yfinance chain reachable:                {'YES' if yf_ok else 'NO'}")
    # Non-zero exit if either path failed outright, so the result is scriptable.
    sys.exit(0 if (alpaca_ok and yf_ok) else 1)


if __name__ == "__main__":
    main()
