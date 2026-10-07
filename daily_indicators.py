"""Daily indicators for the dashboard's technical-alerts tab (read-only, never trades).

    python daily_indicators.py        # fetch ~1 year of daily candles for the F&O stocks, write data/reports/daily_indicators.json

Per stock (using completed days only): prior N-day highs/lows (5, 10, 30, 90 days, 52 weeks), 20 EMA, 50/100/200 DMA,
the last close and the 10,3 supertrend state. `enrich_rows` adds the fields the alert rules look for to each live
market-watch row, comparing the live price with those levels:
  range_Nd_breakout / range_Nd_breakdown  - live price beyond the prior N-day high / low
  dmaN_breakout, ema20_breakout           - price crossed that average today (prev close on one side, live price on the other)
  supertrend_direction                    - "up"/"down" only when the live price flips the daily supertrend today
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "reports" / "daily_indicators.json"
RANGES = {"5d": 5, "10d": 10, "30d": 30, "90d": 90, "52w": 250}


def ema(values: Sequence[float], period: int) -> float:
    v = np.asarray(values, dtype=float)
    if len(v) < period:
        return 0.0
    k = 2.0 / (period + 1)
    e = float(v[:period].mean())
    for x in v[period:]:
        e = float(x) * k + e * (1 - k)
    return e


def sma(values: Sequence[float], period: int) -> float:
    v = np.asarray(values, dtype=float)
    return float(v[-period:].mean()) if len(v) >= period else 0.0


def supertrend_state(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 10,
                     mult: float = 3.0) -> dict[str, Any]:
    """Final bands and direction after the last completed bar (direction 1 = up/bullish, -1 = down)."""
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    n = len(c)
    if n <= period + 2:
        return {"direction": 0, "upper": 0.0, "lower": 0.0}
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = np.full(n, np.nan)
    atr[period] = tr[:period].mean()
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period
    hl2 = (h + l) / 2
    ub, lb = hl2 + mult * atr, hl2 - mult * atr
    fub, flb = ub.copy(), lb.copy()
    direction = 1
    for i in range(period + 1, n):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if direction == 1 and c[i] < flb[i]:
            direction = -1
        elif direction == -1 and c[i] > fub[i]:
            direction = 1
    return {"direction": direction, "upper": float(fub[-1]), "lower": float(flb[-1])}


def compute_indicators(high: Sequence[float], low: Sequence[float], close: Sequence[float]) -> dict[str, Any]:
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    out: dict[str, Any] = {"last_close": float(c[-1]) if len(c) else 0.0, "bars": int(len(c))}
    for name, n in RANGES.items():
        if len(h) >= n:
            out[f"hi_{name}"], out[f"lo_{name}"] = float(h[-n:].max()), float(l[-n:].min())
    for n in (50, 100, 200):
        out[f"dma{n}"] = sma(c, n)
    out["ema20"] = ema(c, 20)
    st = supertrend_state(h, l, c)
    out["st_dir"], out["st_upper"], out["st_lower"] = st["direction"], st["upper"], st["lower"]
    return out


def enrich_rows(rows: Sequence[Mapping[str, Any]], indicators: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Add the alert-rule fields to every row; rows without indicators get all fields False/empty (rules stay silent)."""
    out = []
    for row in rows:
        r = dict(row)
        ind = indicators.get(str(r.get("symbol", "")).upper()) or {}
        try:
            ltp = float(r.get("ltp") or 0)
        except (TypeError, ValueError):
            ltp = 0.0
        prev = float(ind.get("last_close") or 0)
        for name in RANGES:
            hi, lo = ind.get(f"hi_{name}"), ind.get(f"lo_{name}")
            r[f"range_{name}_breakout"] = bool(ltp > 0 and hi and ltp > hi)
            r[f"range_{name}_breakdown"] = bool(ltp > 0 and lo and ltp < lo)
        for key, ma_key in (("dma200_breakout", "dma200"), ("dma100_breakout", "dma100"), ("dma50_breakout", "dma50"), ("ema20_breakout", "ema20")):
            ma = float(ind.get(ma_key) or 0)
            r[key] = bool(ltp > 0 and prev > 0 and ma > 0 and ((prev < ma < ltp) or (prev > ma > ltp)))
        flip = ""
        if ltp > 0 and ind.get("st_dir"):
            if ind["st_dir"] == -1 and ltp > float(ind.get("st_upper") or 1e18):
                flip = "up"
            elif ind["st_dir"] == 1 and ltp < float(ind.get("st_lower") or 0):
                flip = "down"
        r["supertrend_direction"] = flip
        out.append(r)
    return out


def load_indicators(path: Path = OUT) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        return {}


def fetch_and_write() -> int:
    import requests
    from dotenv import load_dotenv

    sys.path.insert(0, str(ROOT))
    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token
    from order_book_recorder import _universe

    universe = _universe()
    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    headers = {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}
    today = date.today()
    start = (today - timedelta(days=400)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    session, last, result = requests.Session(), 0.0, {}
    for symbol, security_id in universe.items():
        for attempt in range(4):
            time.sleep(max(0.0, 0.7 - (time.time() - last)))
            last = time.time()
            r = session.post("https://api.dhan.co/v2/charts/historical", headers=headers, timeout=40, json={
                "securityId": str(security_id), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "expiryCode": 0,
                "oi": False, "fromDate": start, "toDate": end})
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            break
        if r.status_code != 200:
            continue
        d = r.json()
        stamps = d.get("timestamp") or []
        if len(stamps) < 30:
            continue
        keep = [i for i, t in enumerate(stamps) if datetime.fromtimestamp(t).date() < today]     # completed days only
        pick = lambda key: [d[key][i] for i in keep]                                             # noqa: E731
        result[symbol] = compute_indicators(pick("high"), pick("low"), pick("close"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated_at": datetime.now().isoformat(), "count": len(result), "symbols": result}), encoding="utf-8")
    print(f"daily indicators for {len(result)} of {len(universe)} stocks -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(fetch_and_write())
