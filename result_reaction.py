"""Results-reaction check (SHADOW: it logs and tags; nothing here allows, blocks or changes a trade).

News text cannot say whether a results announcement was good or bad: a headline reading "profit rises 4.3%" can still be received badly (COLPAL fell 5 % on 4x volume on 23 Oct after exactly that headline).
What does tell is how the stock TRADES after the results. This watches every stock whose results are out and flags a CONFIRMED REACTION when, at the same time,

    results out     a results / board-outcome filing was published in the last RESULT_WINDOW_H hours (announcement feed)
    volume          volume so far is at least RVOL_MIN x the stock's usual volume for this time of day (event_tags.expected_fraction)
    move            the stock is at least MOVE_MIN % away from the previous close, in one direction (no gap needed: COLPAL opened -0.4 % and sold off through the morning)
    VWAP            and it trades on that side of its own VWAP (below it for a fall, above it for a rise)

    data/result_reaction/<day>.csv     one row per watched stock whenever its state changes and at least every LOG_EVERY_MIN minutes
    tags(symbol, direction, now)       shadow tags for a candidate (rx_ prefix): rx_results_age_h, rx_rvol, rx_move_dir_pct (in OUR direction), rx_vs_vwap_dir_pct, rx_pd_break,
                                       rx_confirmed (a reaction is confirmed, either way), rx_with (and it points the way we trade), rx_reaction (= confirmed and with), rx_since (HH:MM first confirmed)

rx_reaction is the condition a later rule could use to let a trade through the "late / extended" entry rules on a results-driven trend day. Whether it should is what the review decides
(result_reaction_review.py joins it with how every skipped signal turned out).
"""

from __future__ import annotations

import csv
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
RESULT_WINDOW_H = 30.0
RVOL_MIN, MOVE_MIN = 3.0, 1.5
LOG_EVERY_MIN = 10
RESULTS_RX = re.compile(r"outcome of board meeting|financial results|results for the quarter|results for the half", re.I)
FIELDS = ["date", "time", "symbol", "age_h", "ltp", "prev_close", "move_prev_pct", "rvol", "vs_vwap_pct", "pd_break", "direction", "confirmed"]
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"day": None, "latest": {}, "first": {}, "logged": {}}
_RES: dict[str, Any] = {"mtime": None, "path": None, "by_symbol": {}}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _parse(ts: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts))
        return d if d.tzinfo else d.replace(tzinfo=IST)
    except ValueError:
        return None


def results_filings(root: Path = ROOT) -> dict[str, list[datetime]]:
    """symbol -> publication times (ascending) of results / board-outcome filings in the announcement feed (cached by file modification time)."""
    path = root / "data" / "news_intelligence" / "announcements.jsonl"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _RES["path"] != str(path) or _RES["mtime"] != mtime:
        by: dict[str, list[datetime]] = {}
        try:
            with path.open(encoding="utf-8") as h:
                for line in h:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if RESULTS_RX.search(f"{r.get('desc', '')} {r.get('text', '')}"):
                        t = _parse(r.get("published_at"))
                        if t and r.get("symbol"):
                            by.setdefault(str(r["symbol"]), []).append(t)
        except OSError:
            return {}
        for v in by.values():
            v.sort()
        _RES.update(path=str(path), mtime=mtime, by_symbol=by)
    return _RES["by_symbol"]


def results_age_h(symbol: str, now: datetime, root: Path = ROOT, filings: Mapping[str, list[datetime]] | None = None) -> float | None:
    """Hours since the stock's latest results filing before `now`, or None when none is within the window."""
    times = [t for t in (filings if filings is not None else results_filings(root)).get(symbol, []) if t <= now]
    if not times:
        return None
    age = (now - times[-1]).total_seconds() / 3600.0
    return round(age, 1) if age <= RESULT_WINDOW_H else None


def evaluate(ltp: float, prev_close: float, volume: float, avg_vol20: float, vwap: float, pdh: float, pdl: float, now: datetime, age_h: float | None) -> dict[str, Any]:
    """The reaction state of one stock right now. Pure; unit tested."""
    from event_tags import expected_fraction, minutes_after_open

    frac = expected_fraction(minutes_after_open(now))
    rvol = volume / (avg_vol20 * frac) if avg_vol20 > 0 and frac > 0.01 else 0.0
    move = (ltp / prev_close - 1.0) * 100.0 if prev_close > 0 and ltp > 0 else 0.0
    direction = "BULLISH" if move > 0 else "BEARISH" if move < 0 else ""
    up = move > 0
    vs_vwap = (ltp / vwap - 1.0) * 100.0 if vwap > 0 and ltp > 0 else 0.0
    beyond_vwap = bool(vwap > 0 and ((ltp > vwap) if up else (ltp < vwap)))
    pd_break = int((pdh > 0 and ltp > pdh) if up else (pdl > 0 and ltp < pdl))
    confirmed = int(age_h is not None and rvol >= RVOL_MIN and abs(move) >= MOVE_MIN and beyond_vwap)
    return {"age_h": age_h, "move_prev_pct": round(move, 2), "rvol": round(rvol, 1), "vs_vwap_pct": round(vs_vwap, 2), "pd_break": pd_break, "direction": direction, "confirmed": confirmed}


def observe(rows: Iterable[Mapping[str, Any]], volumes: Mapping[str, float], indicators: Mapping[str, Any], vwaps: Mapping[str, float], now: datetime, root: Path = ROOT) -> int:
    """Called every scan cycle with the market-watch rows. Updates the live state of every stock whose results are out and appends a log row on a change. Returns rows written."""
    today = now.date().isoformat()
    with _LOCK:
        if _STATE["day"] != today:
            _STATE.update(day=today, latest={}, first={}, logged={})
        filings = results_filings(root)
        out = []
        for r in rows:
            sym = r.get("symbol")
            age = results_age_h(sym, now, root, filings) if sym else None
            if age is None:
                continue
            ind = indicators.get(sym) or {}
            ev = evaluate(_f(r.get("ltp")), _f(r.get("previous_close")), _f(volumes.get(sym)), _f(ind.get("avg_vol20")), _f(vwaps.get(sym)), _f(ind.get("pdh")), _f(ind.get("pdl")), now, age)
            ev["ltp"], ev["prev_close"], ev["time"] = _f(r.get("ltp")), _f(r.get("previous_close")), now.strftime("%H:%M:%S")
            _STATE["latest"][sym] = ev
            if ev["confirmed"] and sym not in _STATE["first"]:
                _STATE["first"][sym] = now.strftime("%H:%M")
            last = _STATE["logged"].get(sym)
            if last is None or last[0] != ev["confirmed"] or (now - last[1]).total_seconds() >= LOG_EVERY_MIN * 60:
                _STATE["logged"][sym] = (ev["confirmed"], now)
                out.append({"date": today, "symbol": sym, **{k: ev.get(k, "") for k in FIELDS if k not in ("date", "symbol")}})
    if out:
        path = root / "data" / "result_reaction" / f"{today}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(out)
    return len(out)


def tags(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    """Shadow tags for a candidate from the live state (the scan loop and the journal share the process). {} when the stock's results are not out."""
    try:
        with _LOCK:
            ev = _STATE["latest"].get(symbol) if _STATE["day"] == now.date().isoformat() else None
            since = _STATE["first"].get(symbol, "")
        if not ev:
            return {}
        sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
        with_us = int(ev["direction"] == str(direction).upper())
        return {"rx_results_age_h": ev["age_h"], "rx_rvol": ev["rvol"], "rx_move_dir_pct": round(sign * ev["move_prev_pct"], 2), "rx_vs_vwap_dir_pct": round(sign * ev["vs_vwap_pct"], 2),
                "rx_pd_break": ev["pd_break"], "rx_confirmed": ev["confirmed"], "rx_with": with_us, "rx_reaction": int(ev["confirmed"] and with_us), "rx_since": since}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
