"""Price zones for the stock chart: where the stock has turned back before, plus the standard reference levels. Read-only.

Zones are calculated from past candles with plain rules (nothing is predicted):
  supply / demand   price areas where hourly swing highs / lows of the last 10 sessions clustered (at least 2 turns in the area)
  pivot             classic pivot lines from the previous session: P, R1, R2, R3, S1, S2, S3
  pd                previous-day high and low
  or                today's opening range (first 30 minutes) high and low
  gap               the unfilled area between the previous close and today's open when the gap is 0.5% or more
  vwap              today's volume-weighted average price (a line series)
Every zone carries how many times it held (`touches`) so a strong area can be told from a weak one.
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
HISTORY_DAYS = 10
CLUSTER_TOL = 0.004          # swing points within 0.4% of each other belong to one zone
MAX_DISTANCE = 0.06          # only zones within 6% of the current price are drawn
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def hourly(m5: pd.DataFrame) -> pd.DataFrame:
    work = m5.copy()
    work["day"] = work.index.normalize()
    work["hb"] = ((work.index - work["day"] - pd.Timedelta(hours=9, minutes=15)) // pd.Timedelta(hours=1)).astype(int)
    return work.groupby(["day", "hb"]).agg(h=("h", "max"), l=("l", "min"), c=("c", "last")).reset_index()


def swing_points(h: np.ndarray, l: np.ndarray, k: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    for i in range(k, len(h) - k):
        if h[i] >= h[i - k:i + k + 1].max():
            highs.append((i, float(h[i])))
        if l[i] <= l[i - k:i + k + 1].min():
            lows.append((i, float(l[i])))
    return highs, lows


def cluster(points: list[tuple[int, float]], tol: float = CLUSTER_TOL) -> list[dict[str, Any]]:
    """Greedy clustering of swing levels; returns zones with their span, touch count and the index of the latest touch."""
    out: list[dict[str, Any]] = []
    for idx, price in sorted(points, key=lambda p: p[1]):
        if out and price <= out[-1]["mean"] * (1 + tol):
            z = out[-1]
            z["vals"].append(price)
            z["idx"].append(idx)
            z["mean"] = float(np.mean(z["vals"]))
        else:
            out.append({"vals": [price], "idx": [idx], "mean": price})
    return [{"low": min(z["vals"]), "high": max(z["vals"]), "touches": len(z["vals"]), "last": max(z["idx"])} for z in out]


def pivot_levels(prev_day: pd.DataFrame) -> dict[str, float]:
    high, low, close = float(prev_day.h.max()), float(prev_day.l.min()), float(prev_day.c.iloc[-1])
    p = (high + low + close) / 3.0
    return {"P": p, "R1": 2 * p - low, "R2": p + (high - low), "R3": high + 2 * (p - low), "S1": 2 * p - high, "S2": p - (high - low), "S3": low - 2 * (high - p)}


def build_zones(m5: pd.DataFrame, today: pd.Timestamp, price: float, history_days: int = HISTORY_DAYS) -> dict[str, Any]:
    """m5: 5-minute bars (index = bar start; columns o,h,l,c,v) covering the sessions before `today` and, optionally, today so far."""
    today = pd.Timestamp(today).normalize()
    past = m5[m5.index.normalize() < today]
    days = sorted(past.index.normalize().unique())
    if len(days) < 3:
        return {"zones": [], "vwap": []}
    hist = past[past.index.normalize() >= days[-history_days]] if len(days) >= history_days else past
    hb = hourly(hist)
    zones: list[dict[str, Any]] = []
    highs, lows = swing_points(hb.h.values.astype(float), hb.l.values.astype(float))
    n = len(hb)
    for kind, pts in (("supply", highs), ("demand", lows)):
        for z in cluster(pts):
            if z["touches"] < 2:
                continue
            mid = (z["low"] + z["high"]) / 2
            if price > 0 and abs(mid / price - 1) > MAX_DISTANCE:
                continue
            pad = mid * 0.0008
            zones.append({"kind": kind, "name": f"{'Supply' if kind == 'supply' else 'Demand'} x{z['touches']}", "low": round(z["low"] - pad, 2), "high": round(z["high"] + pad, 2),
                          "touches": z["touches"], "recency": round(z["last"] / max(n - 1, 1), 2)})
    zones.sort(key=lambda z: (-z["touches"], -z["recency"]))
    zones = [z for z in zones if z["kind"] == "supply"][:4] + [z for z in zones if z["kind"] == "demand"][:4]
    prev = past[past.index.normalize() == days[-1]]
    lv = pivot_levels(prev)
    for name, val in lv.items():
        if price <= 0 or abs(val / price - 1) <= MAX_DISTANCE:
            zones.append({"kind": "pivot", "name": name, "low": round(val, 2), "high": round(val, 2), "touches": 0})
    zones.append({"kind": "pd", "name": "PDH", "low": round(float(prev.h.max()), 2), "high": round(float(prev.h.max()), 2), "touches": 0})
    zones.append({"kind": "pd", "name": "PDL", "low": round(float(prev.l.min()), 2), "high": round(float(prev.l.min()), 2), "touches": 0})
    vwap: list[dict[str, float]] = []
    now_bars = m5[m5.index.normalize() == today]
    if len(now_bars):
        first30 = now_bars[(now_bars.index.hour * 60 + now_bars.index.minute) < 9 * 60 + 45]
        if len(first30) >= 3:
            zones.append({"kind": "or", "name": "OR high", "low": round(float(first30.h.max()), 2), "high": round(float(first30.h.max()), 2), "touches": 0})
            zones.append({"kind": "or", "name": "OR low", "low": round(float(first30.l.min()), 2), "high": round(float(first30.l.min()), 2), "touches": 0})
        prev_close, op = float(prev.c.iloc[-1]), float(now_bars.o.iloc[0])
        if prev_close > 0 and abs(op / prev_close - 1) >= 0.005:
            lo, hi = sorted((prev_close, op))
            filled = bool((now_bars.l.min() <= lo) if op > prev_close else (now_bars.h.max() >= hi))
            zones.append({"kind": "gap", "name": "Gap up (filled)" if op > prev_close and filled else "Gap up" if op > prev_close else "Gap down (filled)" if filled else "Gap down",
                          "low": round(lo, 2), "high": round(hi, 2), "touches": 0})
        tp = (now_bars.h + now_bars.l + now_bars.c) / 3.0
        vol = now_bars.v.astype(float).cumsum().replace(0, np.nan)
        vw = ((tp * now_bars.v.astype(float)).cumsum() / vol).ffill()
        vwap = [{"t": int(ts.tz_localize("UTC").timestamp()), "v": round(float(v), 2)} for ts, v in vw.dropna().items()]   # same IST-as-UTC axis as the candles
    return {"zones": zones, "vwap": vwap}


def fetch_history(security_id: int, days: int = 16) -> pd.DataFrame | None:
    """Last `days` calendar days of 5-minute bars (incl. today so far) from Dhan, one call."""
    import requests
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    sys_path = str(ROOT)
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    start = (date.today() - timedelta(days=days)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()
    r = requests.post("https://api.dhan.co/v2/charts/intraday", timeout=30, json={
        "securityId": str(int(security_id)), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "interval": "5", "oi": False,
        "fromDate": f"{start} 09:15:00", "toDate": f"{end} 15:30:00"},
        headers={"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"})
    if r.status_code != 200:
        return None
    d = r.json()
    if not d.get("timestamp"):
        return None
    t = pd.to_datetime(d["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
    return pd.DataFrame({"o": d["open"], "h": d["high"], "l": d["low"], "c": d["close"], "v": d["volume"]}, index=t)


def zones_for(symbol: str, security_id: int, price: float, today: date | None = None) -> dict[str, Any]:
    """Cached (10 minutes) zones for one stock; {} on any failure so the chart still loads."""
    cached = _CACHE.get(symbol)
    if cached and time.time() - cached[0] < 600:
        return cached[1]
    try:
        df = fetch_history(security_id)
        out = build_zones(df, pd.Timestamp(today or date.today()), price) if df is not None else {"zones": [], "vwap": []}
    except Exception:                                      # noqa: BLE001
        out = {"zones": [], "vwap": []}
    _CACHE[symbol] = (time.time(), out)
    return out
