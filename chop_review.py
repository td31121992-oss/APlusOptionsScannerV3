"""Shadow replay of the choppiness measures over every past signal (research only - changes nothing).

For each signal in data/missed_opportunities/<day>/option_returns.json (ATM option bought at the first ENTRY_READY candle, held to
close, hindsight) it computes the choppiness measures from that day's saved 5-minute candles (data/pattern_log/candles/<day>.json)
up to the signal time, then groups outcomes by chop state, side and time of day.

    python chop_review.py        writes data/shadow_rules/chop_review.md and prints it
"""

from __future__ import annotations

import glob
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

import chop

ROOT = Path(__file__).resolve().parent
FIRST_DAY = "2026-10-01"


def _mins(h: Any) -> int:
    a, b = str(h).split(":")[:2]
    return int(a) * 60 + int(b)


def build_rows(root: Path = ROOT, first_day: str = FIRST_DAY) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "missed_opportunities" / "20*" / "option_returns.json"))):
        day = Path(p).parent.name
        if day < first_day:
            continue
        cf = root / "data" / "pattern_log" / "candles" / f"{day}.json"
        try:
            symbols = json.loads(cf.read_text(encoding="utf-8")).get("symbols", {})
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in data:
            if r.get("kind") != "ATM":
                continue
            s = symbols.get(r["symbol"])
            if not s:
                continue
            try:
                t = _mins(r["ready"])
            except ValueError:
                continue
            idx = [i for i, m in enumerate(s["minute"]) if m < t]
            if len(idx) < chop.MIN_BARS:
                continue
            cs = [{"o": s["open"][i], "h": s["high"][i], "l": s["low"][i], "c": s["close"][i], "v": s["volume"][i]} for i in idx]
            m = chop.measures(cs)
            if not m:
                continue
            fate = str(r.get("fate") or "")
            rows.append({"day": day, "symbol": r["symbol"], "dir": r["dir"], "ready": r["ready"], "minute": t,
                         "fate": "TRADED" if fate == "TRADED" else ("V2" if fate.startswith("V2_BLOCKED") else "A+" if fate.startswith("A_PLUS") else "OTHER"),
                         "best": float(r.get("best") or 0), "worst": float(r.get("worst") or 0), "close": float(r.get("close") or 0),
                         "stop_first": bool(r.get("stop_first")), **m})
    return rows


def _line(g: list[dict[str, Any]]) -> str:
    n = len(g)
    if n == 0:
        return "| 0 | - | - | - | - | - |"
    return (f"| {n} | {100 * sum(x['best'] >= 15 for x in g) / n:.0f}% | {100 * sum(x['best'] >= 30 for x in g) / n:.0f}% | "
            f"{100 * sum(x['stop_first'] for x in g) / n:.0f}% | {st.mean(x['close'] for x in g):+.1f}% | {100 * sum(x['close'] > 0 for x in g) / n:.0f}% |")


def render(rows: list[dict[str, Any]]) -> str:
    out = ["# Choppiness at entry: shadow replay", "",
           f"{len(rows)} signals across {len({r['day'] for r in rows})} day(s). ATM option bought at the first ENTRY_READY candle, held to close, "
           "hindsight, before costs. Chop is measured from the 5-minute candles up to that moment (see chop.py for the definitions).", "",
           "## All signals by chop state", "", "| State | n | +15% | +30% | Stop first | Mean close | Closed up |", "|---|---|---|---|---|---|---|"]
    for state in ("TRENDING", "MIXED", "CHOPPY"):
        out.append(f"| {state} " + _line([r for r in rows if r["chop_state"] == state]))
    out += ["", "## Traded signals only", "", "| State | n | +15% | +30% | Stop first | Mean close | Closed up |", "|---|---|---|---|---|---|---|"]
    for state in ("TRENDING", "MIXED", "CHOPPY"):
        out.append(f"| {state} " + _line([r for r in rows if r["fate"] == "TRADED" and r["chop_state"] == state]))
    for side in ("BULLISH", "BEARISH"):
        out += ["", f"## {side.title()} signals", "", "| State | n | +15% | +30% | Stop first | Mean close | Closed up |", "|---|---|---|---|---|---|---|"]
        for state in ("TRENDING", "MIXED", "CHOPPY"):
            out.append(f"| {state} " + _line([r for r in rows if r["dir"] == side and r["chop_state"] == state]))
    out += ["", "## By time of day (all signals)", "", "| Window | State | n | +15% | +30% | Stop first | Mean close | Closed up |", "|---|---|---|---|---|---|---|---|"]
    for lab, lo, hi in (("before 10:30", 0, 630), ("10:30-13:00", 630, 780), ("13:00+", 780, 1440)):
        for state in ("TRENDING", "CHOPPY"):
            out.append(f"| {lab} | {state} " + _line([r for r in rows if lo <= r["minute"] < hi and r["chop_state"] == state]))
    out += ["", "## VWAP crosses in the last 60 minutes", "", "| Crosses | n | +15% | +30% | Stop first | Mean close | Closed up |", "|---|---|---|---|---|---|---|"]
    for lab, lo, hi in (("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3+", 3, 99)):
        out.append(f"| {lab} " + _line([r for r in rows if lo <= r["chop_vwap_x60"] <= hi]))
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_day[r["day"]].append(r)
    out += ["", "## By day: trending vs choppy mean close", "", "| Day | Trending n / mean | Choppy n / mean |", "|---|---|---|"]
    for d in sorted(by_day):
        t = [x["close"] for x in by_day[d] if x["chop_state"] == "TRENDING"]
        c = [x["close"] for x in by_day[d] if x["chop_state"] == "CHOPPY"]
        out.append(f"| {d} | {len(t)} / {st.mean(t):+.1f}% | {len(c)} / {st.mean(c):+.1f}% |" if t and c else
                   f"| {d} | {len(t)} / {(st.mean(t) if t else 0):+.1f}% | {len(c)} / {(st.mean(c) if c else 0):+.1f}% |")
    out += ["", "_Research only. A difference that appears on several days and in both directions is worth acting on; a single day is not._", ""]
    return "\n".join(out)


def write(root: Path = ROOT) -> Path | None:
    rows = build_rows(root)
    if not rows:
        return None
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "chop_review.md"
    path.write_text(render(rows), encoding="utf-8")
    return path


def main() -> int:
    p = write()
    print(p.read_text(encoding="utf-8") if p else "no candles / option returns on file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
