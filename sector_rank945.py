"""The 09:45 sector picks of the "observe until 09:45, then trade only the top-2 gaining / top-2 losing sectors" strategy (read-only research helpers; no trading effect).

Shared by sector_focus_replay.py (the replay on past trades) and derived_tags.py (the forward tags).

At 09:45 each F&O stock's move is taken from the last 5-minute bar that starts before 09:45, either since the 09:15 open ("open") or since the previous close ("prev"). A sector's move is the
median of its stocks (sectors with at least 4 stocks; UNCLASSIFIED left out). The 2 best sectors are the gaining sectors, the 2 worst the losing sectors. Calls are allowed only in a gaining
sector, puts only in a losing sector, never before 09:45, and optionally only in the strongest N movers of that sector on the trade's side.
"""

from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
CUT_MIN = 9 * 60 + 45                                        # 09:45
OPEN_MIN = 9 * 60 + 15
MIN_SECTOR = 4


def load_day(day: str, root: Path = ROOT) -> dict[str, dict[str, Any]]:
    try:
        return json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        return {}


def sector_labels(root: Path = ROOT) -> dict[str, str]:
    try:
        rows = json.loads((root / "data" / "reports" / "fno_market_watch_latest.json").read_text(encoding="utf-8")).get("rows", [])
    except (OSError, ValueError):
        return {}
    return {str(r.get("symbol") or "").upper(): str(r.get("sector") or "") for r in rows if r.get("symbol")}


def moves_at_cut(symbols: Mapping[str, Mapping[str, Any]], prev_close: Mapping[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """(% move since the 09:15 open, % move since the previous close) of each stock at 09:45."""
    from_open: dict[str, float] = {}
    from_prev: dict[str, float] = {}
    for sym, d in symbols.items():
        mins, opens, closes = d.get("minute") or [], d.get("open") or [], d.get("close") or []
        if not mins or OPEN_MIN not in mins:
            continue
        idx = [i for i, m in enumerate(mins) if m < CUT_MIN]
        if not idx:
            continue
        o, c = opens[mins.index(OPEN_MIN)], closes[idx[-1]]
        if o and o > 0:
            from_open[sym.upper()] = (c / o - 1) * 100
        if prev_close.get(sym.upper()):
            from_prev[sym.upper()] = (c / prev_close[sym.upper()] - 1) * 100
    return from_open, from_prev


def rank_sectors(move: Mapping[str, float], sectors: Mapping[str, str]) -> tuple[list[str], dict[str, float]]:
    by: dict[str, list[float]] = defaultdict(list)
    for s, m in move.items():
        sec = sectors.get(s, "")
        if sec and sec != "UNCLASSIFIED":
            by[sec].append(m)
    med = {k: st.median(v) for k, v in by.items() if len(v) >= MIN_SECTOR}
    return sorted(med, key=lambda k: -med[k]), med


def previous_close(day: str, root: Path = ROOT) -> dict[str, float]:
    """Last close of every stock on the session before `day` (the previous candle file)."""
    folder = root / "data" / "pattern_log" / "candles"
    earlier = sorted(p.stem for p in folder.glob("*.json") if p.stem < day)
    if not earlier:
        return {}
    return {sym.upper(): d["close"][-1] for sym, d in load_day(earlier[-1], root).items() if d.get("close")}


_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def day_picks(day: str, root: Path = ROOT, sectors: Mapping[str, str] | None = None) -> dict[str, Any]:
    """{"open": picks, "prev": picks} for the day; a basis is missing when the candles / sectors cannot rank at least 5 sectors. picks = gain / lose (sector names), stocks (sector ->
    its stocks, strongest gainer first) and med (sector -> median move). Cached per (root, day) once the day's candle file exists."""
    key = (str(root), day)
    if key in _CACHE:
        return _CACHE[key]
    symbols = load_day(day, root)
    out: dict[str, Any] = {}
    if symbols:
        labels = sectors if sectors is not None else sector_labels(root)
        fo, fp = moves_at_cut(symbols, previous_close(day, root))
        for basis, mv in (("open", fo), ("prev", fp)):
            order, med = rank_sectors(mv, labels)
            if len(order) >= 5:
                stocks = {sec: sorted((s for s in mv if labels.get(s) == sec), key=lambda s: -mv[s]) for sec in order}
                out[basis] = {"gain": order[:2], "lose": order[-2:], "stocks": stocks, "med": med}
        _CACHE[key] = out
    return out


def allowed(symbol: str, side: str, minute_of_day: int, picks: Mapping[str, Any] | None, sectors: Mapping[str, str], top_n: int | None = None, absolute: bool = False) -> bool | None:
    """Would the strategy have taken this trade? None when there are no picks for the day. `absolute`: the sector must also be moving the right way (gaining sectors up, losing sectors down)."""
    if not picks:
        return None
    if minute_of_day < CUT_MIN:
        return False
    sym, side = str(symbol).upper(), str(side).upper()
    sec = sectors.get(sym, "")
    if side == "CE" and sec in picks["gain"]:
        order = picks["stocks"][sec]
        if absolute and picks["med"][sec] < 0:
            return False
    elif side == "PE" and sec in picks["lose"]:
        order = picks["stocks"][sec][::-1]                                                       # strongest faller first
        if absolute and picks["med"][sec] > 0:
            return False
    else:
        return False
    return top_n is None or sym in order[:top_n]
