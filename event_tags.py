"""Event-day tags (SHADOW only: nothing here blocks or changes a trade).

An EVENT-LIKE stock is one that opened with a gap of at least 2% on at least 2x its normal volume for the time of day - how a results or news
reaction looks in price data (we keep no historical event calendar). Two things are recorded:

  1. On every paper trade: event_like, event_gap_pct, event_rvol, event_move_open_pct and event_agrees (the move since the open points the
     same way as the gap), so event trades can be compared with all other trades later.
  2. A checkpoint log of EVERY event-like stock at 09:20, 09:30, 09:45 and 10:00 (data/event_days/<date>.csv) with the gap, the move since the
     open and whether it still agrees with the gap. Our test on 5 weeks of data found that stocks still moving in the gap direction at 10:00
     hit a +0.6% stock move before -0.8% in 80% of 25 cases (against 33% when the move had reversed the gap); the log lets us check that forward.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent
GAP_MIN, RVOL_MIN = 2.0, 2.0
CHECKPOINTS = ("09:20", "09:30", "09:45", "10:00")
FIELDS = ["date", "checkpoint", "time", "symbol", "sector", "gap_pct", "move_from_open_pct", "rvol_est", "agrees", "ltp"]
# median share of the day's volume traded by this time (minutes after 09:15), measured on 35 sessions x 213 stocks
_FRACTION = [(0, 0.0), (5, 0.038), (10, 0.061), (15, 0.079), (30, 0.129), (45, 0.171), (60, 0.212), (105, 0.315), (375, 1.0)]


def expected_fraction(minutes_after_open: float) -> float:
    m = max(0.0, float(minutes_after_open))
    for (m0, f0), (m1, f1) in zip(_FRACTION, _FRACTION[1:]):
        if m <= m1:
            return f0 + (f1 - f0) * ((m - m0) / (m1 - m0) if m1 > m0 else 0.0)
    return 1.0


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def minutes_after_open(now: datetime) -> float:
    return now.hour * 60 + now.minute + now.second / 60.0 - (9 * 60 + 15)


def evaluate(row: Mapping[str, Any], volume_so_far: float, avg_vol20: float, now: datetime) -> dict[str, Any]:
    """row: a market-watch row (gap_pct, from_open_pct, ...). Returns the event tags for this stock right now."""
    gap, move = _f(row.get("gap_pct")), _f(row.get("from_open_pct"))
    frac = expected_fraction(minutes_after_open(now))
    rvol = volume_so_far / (avg_vol20 * frac) if avg_vol20 > 0 and frac > 0.01 else 0.0
    like = abs(gap) >= GAP_MIN and rvol >= RVOL_MIN
    agrees = (gap > 0 and move > 0) or (gap < 0 and move < 0)
    return {"event_like": bool(like), "event_gap_pct": round(gap, 2), "event_rvol": round(rvol, 1),
            "event_move_open_pct": round(move, 2), "event_agrees": bool(agrees)}


def trade_tags(symbol: str, rows: Iterable[Mapping[str, Any]], volumes: Mapping[str, float], indicators: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    row = next((r for r in rows if r.get("symbol") == symbol), None)
    if row is None:
        return {}
    return evaluate(row, _f(volumes.get(symbol)), _f((indicators.get(symbol) or {}).get("avg_vol20")), now)


def observe(rows: Iterable[Mapping[str, Any]], volumes: Mapping[str, float], indicators: Mapping[str, Any], now: datetime,
            state: dict[str, Any], root: Path = ROOT) -> int:
    """Called every scan cycle. At each checkpoint (the first cycle at or after 09:20 / 09:30 / 09:45 / 10:00) writes one row per event-like
    stock. `state` remembers which checkpoints are done today. Returns the number of rows written."""
    today = now.date().isoformat()
    if state.get("day") != today:
        state.clear()
        state["day"], state["done"] = today, set()
    hm = now.strftime("%H:%M")
    due = [c for c in CHECKPOINTS if hm >= c and c not in state["done"]]
    if not due or hm > "10:30":
        return 0
    cp = due[-1]                                           # a late first cycle logs the latest due checkpoint only
    rows = list(rows)
    out = []
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue
        t = evaluate(r, _f(volumes.get(sym)), _f((indicators.get(sym) or {}).get("avg_vol20")), now)
        if t["event_like"]:
            out.append({"date": today, "checkpoint": cp, "time": now.strftime("%H:%M:%S"), "symbol": sym, "sector": r.get("sector", ""),
                        "gap_pct": t["event_gap_pct"], "move_from_open_pct": t["event_move_open_pct"], "rvol_est": t["event_rvol"],
                        "agrees": int(t["event_agrees"]), "ltp": _f(r.get("ltp"))})
    for c in due:
        state["done"].add(c)
    if out:
        path = root / "data" / "event_days" / f"{today}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            w = csv.DictWriter(handle, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(out)
    return len(out)
