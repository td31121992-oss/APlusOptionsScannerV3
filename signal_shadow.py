"""Forward shadow scoring for rules that act on signals we did NOT trade (so no paper trade exists to score). Recording only; nothing here trades or blocks.

A "signal" experiment key is  <GROUP>:<DIRECTION>  e.g.  EXTENDED_WAIT:BULLISH.  For each session after the registration day it takes the FIRST signal per stock in that group/direction
(before 14:30), looks at the stock's own 1-minute price from that minute to 15:15 (data/chart_history/<day>/market_watch_1m.csv) and records the move in the signal's direction.
It is the STOCK price move, not option P&L, and ignores costs: a positive number means the held-back setups would have gone the right way, not that they would have made money.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent


def group_of(status: str) -> str:
    s = str(status)
    if s == "PASSED_ALL_GATES":
        return "PASSED"
    if s.startswith("A_PLUS_WAIT_LATE_") or s == "A_PLUS_WAIT_OVEREXTENDED":
        return "EXTENDED_WAIT"
    if s.startswith("A_PLUS_WAIT"):
        return "OTHER_WAIT"
    if s.startswith("V2_STOCK"):
        return "V2_BLOCK"
    return "OTHER"


def day_moves(day: str, group: str, direction: str) -> list[float]:
    f, m = ROOT / "data" / "signal_snapshots" / f"{day}.csv", ROOT / "data" / "chart_history" / day / "market_watch_1m.csv"
    if not (f.exists() and m.exists()):
        return []
    s = pd.read_csv(f, usecols=["time", "symbol", "direction", "status"])
    s = s[s.direction == direction]
    s = s[s.status.map(group_of) == group]
    if s.empty:
        return []
    s["ts"] = pd.to_datetime(s.time.str[:19])
    s = s.sort_values("ts").drop_duplicates("symbol")
    w = pd.read_csv(m, usecols=["timestamp", "symbol", "ltp"])
    w["ts"] = pd.to_datetime(w.timestamp.astype(str).str[:19])
    px = {k: g.sort_values("ts").set_index("ts").ltp for k, g in w.groupby("symbol")}
    sign = 1 if direction == "BULLISH" else -1
    end, out = pd.Timestamp(f"{day} 15:15"), []
    for r in s.itertuples():
        p = px.get(r.symbol)
        if p is None or r.ts.time() >= pd.Timestamp("14:30").time():
            continue
        fut = p[(p.index >= r.ts) & (p.index <= end)]
        if len(fut) >= 5:
            out.append(sign * (fut.iloc[-1] / fut.iloc[0] - 1) * 100)
    return out


def score(key: str, registered: str, today: str) -> dict:
    """sessions seen after the registration day, signals counted, average % move to 15:15, share of sessions whose average was positive."""
    group, _, direction = key.partition(":")
    days = sorted(p.stem for p in (ROOT / "data" / "signal_snapshots").glob("20??-??-??.csv") if registered < p.stem <= today)
    per_day = {d: v for d in days if (v := day_moves(d, group, direction))}
    allv = [x for v in per_day.values() for x in v]
    pos = [1 for v in per_day.values() if sum(v) / len(v) > 0]
    return {"sessions": len(per_day), "signals": len(allv), "avg_move_pct": (sum(allv) / len(allv)) if allv else None,
            "pos_days": round(100 * len(pos) / len(per_day)) if per_day else None}
