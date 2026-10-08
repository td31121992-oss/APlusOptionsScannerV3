"""Read-only comparison of Upstox market data with Dhan's, to decide whether live data can move to Upstox's free API.

    python upstox_probe.py mapping     # no token needed: maps our 213 F&O stocks to Upstox instrument keys (public file)
    python upstox_probe.py compare     # needs UPSTOX_ANALYTICS_TOKEN in .env: quotes + 5-minute candles, Upstox vs Dhan

Never places orders and never prints a token. The token is read from the environment / .env only.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
CACHE = ROOT / "data" / "cache" / "upstox_NSE.json.gz"
INDEXES = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank", "VIX": "NSE_INDEX|India VIX"}


def load_master() -> list[dict]:
    import requests

    if not CACHE.exists() or time.time() - CACHE.stat().st_mtime > 86400:
        r = requests.get(MASTER_URL, timeout=60)
        r.raise_for_status()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(r.content)
    return json.loads(gzip.decompress(CACHE.read_bytes()).decode("utf-8"))


def fno_universe() -> list[str]:
    from order_book_recorder import _universe

    return sorted(_universe())


def mapping() -> dict[str, dict]:
    master = load_master()
    eq = {x["trading_symbol"]: x for x in master if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"}
    opts: dict[str, int] = {}
    for x in master:
        pass
    out, missing = {}, []
    for s in fno_universe():
        hit = eq.get(s)
        if hit:
            out[s] = {"key": hit["instrument_key"], "name": hit.get("name")}
        else:
            missing.append(s)
    print(f"Upstox master rows: {len(master):,} (NSE segment file)")
    print(f"our F&O stocks mapped to an Upstox NSE_EQ key: {len(out)} of {len(out) + len(missing)}")
    print("not found by trading symbol:", missing[:40])
    return out


def compare() -> int:
    import requests
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    token = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()
    if not token:
        print("UPSTOX_ANALYTICS_TOKEN is not set in .env - add it yourself (do not paste it into chat), then run again.")
        return 2
    m = mapping()
    sample = [s for s in ("RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN", "BHARTIARTL", "ADANIPOWER", "JUBLFOOD", "TRENT", "PNB") if s in m]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    keys = ",".join(m[s]["key"] for s in sample)
    t0 = time.time()
    r = requests.get("https://api.upstox.com/v2/market-quote/quotes", params={"instrument_key": keys}, headers=headers, timeout=30)
    print(f"\nUpstox full quote for {len(sample)} stocks: HTTP {r.status_code} in {time.time() - t0:.2f}s")
    if r.status_code != 200:
        print(r.text[:300])
        return 1
    up = {v["symbol"]: v for v in r.json().get("data", {}).values()}
    # Dhan side
    from dhan_auth import resolve_access_token
    from order_book_recorder import _universe

    uni = _universe()
    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    dtoken = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    dh = {"access-token": dtoken, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}
    t1 = time.time()
    d = requests.post("https://api.dhan.co/v2/marketfeed/quote", json={"NSE_EQ": [uni[s] for s in sample]}, headers=dh, timeout=30)
    print(f"Dhan quote for the same stocks: HTTP {d.status_code} in {time.time() - t1:.2f}s")
    dq = {s: d.json()["data"]["NSE_EQ"].get(str(uni[s])) for s in sample} if d.status_code == 200 else {}
    print(f"\n{'stock':11s}{'Upstox ltp':>11s}{'Dhan ltp':>10s}{'diff':>7s} | {'volume U / D':>26s} | {'avg px U / D':>20s} | depth U/D | buy/sell qty U / D")
    for s in sample:
        u = next((v for k, v in up.items() if s in k or v.get("instrument_token") == m[s]["key"]), None) or {}
        q = dq.get(s) or {}
        ul, dl = float(u.get("last_price") or 0), float(q.get("last_price") or 0)
        print(f"{s:11s}{ul:11.2f}{dl:10.2f}{ul - dl:7.2f} | {int(u.get('volume') or 0):>12,}/{int(q.get('volume') or 0):<12,} | "
              f"{float(u.get('average_price') or 0):9.2f}/{float(q.get('average_price') or 0):<9.2f} | {len((u.get('depth') or {}).get('buy', []))}/{len((q.get('depth') or {}).get('buy', []))} | "
              f"{int(u.get('total_buy_quantity') or 0):,}/{int(u.get('total_sell_quantity') or 0):,} vs {int(q.get('buy_quantity') or 0):,}/{int(q.get('sell_quantity') or 0):,}")
    # one big batch to prove the 500-per-call claim and measure speed
    allkeys = ",".join(v["key"] for v in list(m.values())[:213])
    t2 = time.time()
    big = requests.get("https://api.upstox.com/v2/market-quote/quotes", params={"instrument_key": allkeys}, headers=headers, timeout=60)
    print(f"\nUpstox full quote for all {min(213, len(m))} stocks in one call: HTTP {big.status_code}, {len(big.json().get('data', {})) if big.status_code == 200 else 0} returned, {time.time() - t2:.2f}s")
    # 5-minute candles
    c = requests.get(f"https://api.upstox.com/v3/historical-candle/intraday/{m[sample[0]]['key']}/minutes/5", headers=headers, timeout=30)
    cs = c.json().get("data", {}).get("candles", []) if c.status_code == 200 else []
    print(f"Upstox 5-minute candles for {sample[0]} today: HTTP {c.status_code}, {len(cs)} candles")
    for name, key in INDEXES.items():
        i = requests.get("https://api.upstox.com/v2/market-quote/ltp", params={"instrument_key": key}, headers=headers, timeout=20)
        print(f"index {name}: HTTP {i.status_code}", str(i.json().get("data", ""))[:90] if i.status_code == 200 else i.text[:80])
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "mapping"
    if mode == "compare":
        raise SystemExit(compare())
    mapping()
