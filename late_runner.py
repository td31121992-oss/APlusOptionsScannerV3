"""Late-runner shadow: would releasing the 'late / pivot' waits on stocks that are still trending have caught the big option moves? (SHADOW ONLY: a nightly review; nothing trades on it.)

On 26 Oct the biggest option gainers (COFORGE, ATHERENERG, KAYNES, GLENMARK, MANKIND ...) were all seen by the scanner early, but every cycle was held by an A+ wait (LATE_10M_OVERHEAT,
LATE_VWAP_EXTENSION, LATE_SESSION_EXTENSION, LATE_CLOSE_EXTENSION, PIVOT_TO_R1) and they ran for hours. This module asks, per day, from data/signal_snapshots/<day>.csv:

    WAIT rows      the first snapshot of each (stock, direction) held by one of those waits
    QUALIFIED      of those, the ones that were still trending with us on rising volume: price on our side of VWAP, the last 15 minutes moving our way,
                   relative volume >= 1.2, the tape accumulating in our direction, the trend retained, and the price in the outer part of the day's range on our side
    CONTROL        the wait rows that did NOT qualify (so the filter has to beat releasing everything)

Each is followed on the nearest-the-money option of the right side (call for bullish, put for bearish) from data/options_intelligence_upstox/<day>/option_chain_rows.csv.gz:
entry = the ask (else the last price) at the first chain row at or after the snapshot, then peak %, last %, and which came first, +40 % (the user's first target) or -30 % (a stop).

    data/late_runner/ledger.csv   one row per (day, stock, direction): group, wait status, features, option, entry, peak %, last %, first (T1 / SL / OPEN)
    data/late_runner/review.md    qualified vs control vs all waits across the days recorded

    python late_runner.py [YYYY-MM-DD]   rebuild that day (default today) and the review
"""

from __future__ import annotations

import csv
import gzip
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
WAITS = ("A_PLUS_WAIT_LATE_10M_OVERHEAT", "A_PLUS_WAIT_LATE_VWAP_EXTENSION", "A_PLUS_WAIT_LATE_SESSION_EXTENSION", "A_PLUS_WAIT_LATE_CLOSE_EXTENSION", "A_PLUS_WAIT_PIVOT_TO_R1")
MIN_REL_VOLUME = 1.2
MIN_RECENT_15M = 0.3         # % move in our direction over the last 15 minutes
MIN_TAPE = 0.5               # share of the 15-minute tape accumulating in our direction
MIN_RETENTION = 70.0         # % of the trend's best level still held
MIN_RANGE_POS = 70.0         # % of the day's range, measured from the far side (a call near the high, a put near the low)
T1_PCT, SL_PCT = 40.0, -30.0
MAX_CHAIN_GAP_MIN = 10
FIELDS = ["day", "symbol", "direction", "group", "status", "time", "rel_volume", "recent_15m", "vwap_dist", "tape_15m", "retention", "range_pos", "strike", "side", "entry", "peak_pct", "last_pct", "first"]
LEDGER = ("data", "late_runner", "ledger.csv")
REVIEW = ("data", "late_runner", "review.md")


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def qualifies(row: Mapping[str, Any]) -> bool:
    """Still trending with the signal on rising volume (signals in the snapshot are raw: bearish moves are negative)."""
    sign = 1.0 if str(row.get("direction", "")).upper() == "BULLISH" else -1.0
    rng = _f(row.get("range_position_pct"), 50.0)
    return bool(sign * _f(row.get("vwap_dist_pct")) > 0 and sign * _f(row.get("recent_15m_pct")) >= MIN_RECENT_15M and _f(row.get("rel_volume")) >= MIN_REL_VOLUME
                and _f(row.get("tape_acc_15m")) >= MIN_TAPE and _f(row.get("trend_retention_pct")) >= MIN_RETENTION and (rng if sign > 0 else 100.0 - rng) >= MIN_RANGE_POS)


def first_waits(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The first qualifying wait snapshot per (stock, direction), else the first wait snapshot - so a stock that only qualifies later is judged at that later time."""
    by: dict[tuple[str, str], dict[str, Any]] = {}
    qual: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if r.get("status") not in WAITS:
            continue
        key = (str(r.get("symbol")), str(r.get("direction")))
        by.setdefault(key, dict(r))
        if key not in qual and qualifies(r):
            qual[key] = dict(r)
    out = []
    for key, first in by.items():
        pick = qual.get(key)
        out.append({**(pick or first), "group": "QUALIFIED" if pick else "CONTROL"})
    return out


def outcome(series: Sequence[tuple[str, float]], entry: float) -> dict[str, Any]:
    """series: (time, price) after the entry, oldest first."""
    if entry <= 0 or not series:
        return {}
    first = "OPEN"
    peak = last = entry
    for _, p in series:
        peak, last = max(peak, p), p
        if first == "OPEN":
            if p >= entry * (1 + T1_PCT / 100):
                first = "T1"
            elif p <= entry * (1 + SL_PCT / 100):
                first = "SL"
    return {"peak_pct": round((peak / entry - 1) * 100, 1), "last_pct": round((last / entry - 1) * 100, 1), "first": first}


def _chain(root: Path, day: str, symbols: set[str]) -> dict[str, list[dict[str, str]]]:
    path = root / "data" / "options_intelligence_upstox" / day / "option_chain_rows.csv.gz"
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    if not path.exists():
        return out
    with gzip.open(path, "rt", encoding="utf-8", newline="") as h:
        for r in csv.DictReader(h):
            if r.get("symbol") in symbols:
                out[r["symbol"]].append(r)
    return out


def _hhmm(text: str) -> str:
    return text[11:16]


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def follow(rows: Sequence[Mapping[str, str]], direction: str, hhmm: str) -> dict[str, Any]:
    """Pick the nearest-the-money contract of the right side at the first chain row at or after the signal, and follow its price."""
    side = "CE" if str(direction).upper() == "BULLISH" else "PE"
    start = [r for r in rows if r.get("side") == side and _hhmm(r["captured_at"]) >= hhmm and _f(r.get("ltp")) > 0]
    if not start:
        return {}
    t0 = _hhmm(start[0]["captured_at"])
    if _minutes(t0) - _minutes(hhmm) > MAX_CHAIN_GAP_MIN:
        return {}
    at = [r for r in start if _hhmm(r["captured_at"]) == t0]
    expiry = min(r["expiry"] for r in at)
    at = [r for r in at if r["expiry"] == expiry]
    pick = min(at, key=lambda r: abs(_f(r["strike"]) - _f(r["spot"])))
    key = (pick["strike"], pick["expiry"])
    entry = _f(pick.get("ask")) or _f(pick.get("ltp"))
    series = [(_hhmm(r["captured_at"]), _f(r["ltp"])) for r in rows if r.get("side") == side and (r["strike"], r["expiry"]) == key and _hhmm(r["captured_at"]) >= t0 and _f(r.get("ltp")) > 0]
    res = outcome(series, entry)
    return {"strike": _f(pick["strike"]), "side": side, "entry": round(entry, 2), **res} if res else {}


def day_rows(day: str, root: Path) -> list[dict[str, Any]]:
    snap = root / "data" / "signal_snapshots" / f"{day}.csv"
    if not snap.exists():
        return []
    with snap.open(encoding="utf-8", newline="") as h:
        waits = first_waits(list(csv.DictReader(h)))
    chain = _chain(root, day, {w["symbol"] for w in waits})
    out = []
    for w in waits:
        got = follow(chain.get(w["symbol"], []), w["direction"], _hhmm(w["time"]))
        if not got:
            continue
        out.append({"day": day, "symbol": w["symbol"], "direction": w["direction"], "group": w["group"], "status": w["status"].replace("A_PLUS_WAIT_", ""), "time": _hhmm(w["time"]),
                    "rel_volume": w.get("rel_volume"), "recent_15m": w.get("recent_15m_pct"), "vwap_dist": w.get("vwap_dist_pct"), "tape_15m": w.get("tape_acc_15m"),
                    "retention": w.get("trend_retention_pct"), "range_pos": w.get("range_position_pct"), **got})
    return out


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0}
    peaks = [_f(r["peak_pct"]) for r in rows]
    lasts = [_f(r["last_pct"]) for r in rows]
    t1 = sum(1 for r in rows if r["first"] == "T1")
    sl = sum(1 for r in rows if r["first"] == "SL")
    return {"n": n, "t1": t1, "sl": sl, "t1_pct": round(100 * t1 / n), "sl_pct": round(100 * sl / n), "median_peak": round(st.median(peaks), 1), "median_last": round(st.median(lasts), 1),
            "mean_last": round(st.mean(lasts), 1), "big": sum(1 for p in peaks if p >= 100)}


def run(day: str, root: Path = ROOT) -> Path | None:
    new = day_rows(day, root)
    path = root.joinpath(*LEDGER)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = [r for r in _read(path) if r.get("day") != day]
    allrows = old + [{k: ("" if v is None else v) for k, v in r.items()} for r in new]
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(allrows)
    days = sorted({r["day"] for r in allrows})
    lines = ["# Late-runner shadow (nothing trades on this)", "",
             f"Days recorded: {len(days)} ({days[0] if days else '-'} .. {days[-1] if days else '-'}). A wait row = the first snapshot per stock and direction held by a late / pivot wait. "
             f"QUALIFIED = still trending with us on rising volume. Outcome: nearest-the-money option from the first chain row after the signal; T1 = +{T1_PCT:.0f} % before SL = {SL_PCT:.0f} %.", "",
             "| group | signals | +40% first | -30% first | median peak % | median last % | mean last % | peaks 100%+ |", "|---|---|---|---|---|---|---|---|"]
    for name, sel in (("QUALIFIED", [r for r in allrows if r["group"] == "QUALIFIED"]), ("CONTROL (failed the filter)", [r for r in allrows if r["group"] == "CONTROL"]), ("ALL waits released", allrows)):
        s = summary(sel)
        lines.append(f"| {name} | {s['n']} | " + (" | ".join([f"{s['t1']} ({s['t1_pct']}%)", f"{s['sl']} ({s['sl_pct']}%)", str(s["median_peak"]), str(s["median_last"]), str(s["mean_last"]), str(s["big"])]) if s["n"] else "- | - | - | - | - | -") + " |")
    lines += ["", "Judge it only on forward days: the filter has to beat CONTROL, not just be positive. A handful of days say little.", ""]
    q = sorted((r for r in allrows if r["group"] == "QUALIFIED" and r["day"] == day), key=lambda r: -_f(r["peak_pct"]))[:15]
    if q:
        lines += [f"## Qualified today ({day})", "", "| stock | dir | time | wait | entry | peak % | last % | first |", "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r['symbol']} | {r['direction'][:4]} | {r['time']} | {r['status']} | {r['entry']} | {r['peak_pct']} | {r['last_pct']} | {r['first']} |" for r in q]
    out = root.joinpath(*REVIEW)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.now(IST).strftime("%Y-%m-%d")
    print(run(d))
    print(root_review := ROOT.joinpath(*REVIEW).read_text(encoding="utf-8"))
