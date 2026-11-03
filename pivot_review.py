"""Pivot-state / level-break review (research only - changes nothing).

Question (asked 16 Oct 2026): do calls work better after an R1 breakout and puts after an S1 breakdown, and are the A+ gates holding good
ones back? Every signal on file (data/missed_opportunities/<day>/option_returns.json, ATM option bought at the signal, held to close,
hindsight, before costs) is tagged with

    state        the same classic-pivot zone the scanner uses (previous session's high/low/close): ABOVE_R3 ... BELOW_S3
    since_break  minutes since the stock first CLOSED beyond R1 (calls) / S1 (puts) today, blank if it has not

Each night `run()` writes data/shadow_rules/pivot_review/<day>.csv from the saved 5-minute candles (data/pattern_log/candles/<day>.json;
the previous session's close comes from the previous saved file) and `write_summary()` rebuilds data/shadow_rules/pivot_review.md.
Earlier days can be added with `tag_day()` from any 5-minute bars.

Bar for the one rule worth acting on (puts through S1 that A+ held back for a late/extension rule): 30+ signals, 5+ days, mean close > 0
and still > 0 without the best day, and 60%+ of days positive. Anything less is reported as "not yet".

    python pivot_review.py [YYYY-MM-DD]
"""

from __future__ import annotations

import csv
import glob
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
FIELDS = ["day", "symbol", "dir", "ready", "state", "since_break", "fate", "rule", "best", "worst", "close", "stop_first"]
ORDER = ["ABOVE_R3", "R2_TO_R3", "R1_TO_R2", "PIVOT_TO_R1", "S1_TO_PIVOT", "S2_TO_S1", "S3_TO_S2", "BELOW_S3"]
SOFT = ("late_vwap_extension", "late_10m_overheat", "overextended", "late_session_extension", "late_close_extension")
THROUGH_PUT = ("S2_TO_S1", "S3_TO_S2", "BELOW_S3")
THROUGH_CALL = ("ABOVE_R3", "R2_TO_R3", "R1_TO_R2")
MIN_SIGNALS, MIN_DAYS = 30, 5


def pivots(high: float, low: float, close: float) -> dict[str, float]:
    p = (high + low + close) / 3.0
    return {"P": p, "R1": 2 * p - low, "S1": 2 * p - high, "R2": p + (high - low), "S2": p - (high - low),
            "R3": high + 2 * (p - low), "S3": low - 2 * (high - p)}


def state(price: float, v: dict[str, float]) -> str:
    if price >= v["R3"]:
        return "ABOVE_R3"
    if price >= v["R2"]:
        return "R2_TO_R3"
    if price >= v["R1"]:
        return "R1_TO_R2"
    if price >= v["P"]:
        return "PIVOT_TO_R1"
    if price > v["S1"]:
        return "S1_TO_PIVOT"
    if price > v["S2"]:
        return "S2_TO_S1"
    if price > v["S3"]:
        return "S3_TO_S2"
    return "BELOW_S3"


def _mins(h: str) -> int:
    a, b = str(h).split(":")[:2]
    return int(a) * 60 + int(b)


def tag_signal(sig: dict[str, Any], minutes: list[int], closes: list[float], piv: dict[str, float]) -> dict[str, Any] | None:
    """minutes/closes: today's 5-minute bars (bar start minute, close). The price used is the last bar that started at or before the signal."""
    t = _mins(sig["ready"])
    idx = [i for i, m in enumerate(minutes) if m <= t]
    if not idx:
        return None
    bull = sig.get("dir") == "BULLISH"
    lvl = piv["R1"] if bull else piv["S1"]
    first = next((m for m, c in zip(minutes, closes) if (c >= lvl if bull else c <= lvl)), None)
    fate = str(sig.get("fate") or "")
    return {"day": sig["day"], "symbol": sig["symbol"], "dir": sig.get("dir"), "ready": sig["ready"], "state": state(closes[idx[-1]], piv),
            "since_break": (t - first) if first is not None and first <= t else "", "fate": fate.split(":")[0],
            "rule": fate.split(":", 1)[1] if fate.startswith("A_PLUS:") else "", "best": sig.get("best"), "worst": sig.get("worst"),
            "close": sig.get("close"), "stop_first": int(bool(sig.get("stop_first")))}


def tag_day(day: str, signals: list[dict[str, Any]], today: dict[str, tuple[list[int], list[float]]], prev_hlc: dict[str, tuple[float, float, float]]) -> list[dict[str, Any]]:
    out = []
    for s in signals:
        if s["symbol"] not in today or s["symbol"] not in prev_hlc:
            continue
        m, c = today[s["symbol"]]
        row = tag_signal({**s, "day": day}, m, c, pivots(*prev_hlc[s["symbol"]]))
        if row:
            out.append(row)
    return out


def _candles(root: Path, day: str) -> dict[str, Any]:
    try:
        return json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        return {}


def run(day: str | None = None, root: Path = ROOT) -> Path | None:
    day = day or date.today().isoformat()
    today = _candles(root, day)
    prev_days = sorted(Path(p).stem for p in glob.glob(str(root / "data" / "pattern_log" / "candles" / "20*.json")) if Path(p).stem < day)
    if not today or not prev_days:
        return None
    prev = _candles(root, prev_days[-1])
    prev_hlc = {s: (max(d["high"]), min(d["low"]), d["close"][-1]) for s, d in prev.items() if d.get("high")}
    bars = {s: (list(d["minute"]), list(d["close"])) for s, d in today.items() if d.get("minute")}
    try:
        signals = [r for r in json.loads((root / "data" / "missed_opportunities" / day / "option_returns.json").read_text(encoding="utf-8")) if r.get("kind") == "ATM"]
    except (OSError, ValueError):
        return None
    rows = tag_day(day, signals, bars, prev_hlc)
    folder = root / "data" / "shadow_rules" / "pivot_review"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    write_summary(root)
    return path


# ----------------------------------------------------------------------------- report
def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load(root: Path = ROOT) -> list[dict[str, Any]]:
    rows = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "pivot_review" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                r["close"], r["best"] = _f(r["close"]), _f(r["best"])
                r["stop_first"] = int(_f(r["stop_first"]))
                r["since_break"] = int(_f(r["since_break"])) if r.get("since_break") not in ("", None) else None
                rows.append(r)
    return rows


def _line(label: str, g: list[dict[str, Any]]) -> str:
    if not g:
        return f"| {label} | 0 | | | | | |"
    days = defaultdict(list)
    for x in g:
        days[x["day"]].append(x["close"])
    pos = sum(1 for v in days.values() if st.mean(v) > 0)
    n = len(g)
    return (f"| {label} | {n} | {st.mean(x['close'] for x in g):+.1f} | {100 * sum(x['close'] > 0 for x in g) / n:.0f}% | "
            f"{100 * sum(x['best'] >= 15 for x in g) / n:.0f}% | {100 * sum(x['stop_first'] for x in g) / n:.0f}% | {pos}/{len(days)} |")


def verdict(g: list[dict[str, Any]]) -> str:
    if not g:
        return "not yet: no signals"
    days = defaultdict(list)
    for x in g:
        days[x["day"]].append(x["close"])
    miss = []
    if len(g) < MIN_SIGNALS:
        miss.append(f"{len(g)}/{MIN_SIGNALS} signals")
    if len(days) < MIN_DAYS:
        miss.append(f"{len(days)}/{MIN_DAYS} days")
    mean = st.mean(x["close"] for x in g)
    if mean <= 0:
        miss.append(f"mean {mean:+.1f} not positive")
    best = max(days, key=lambda d: sum(days[d]))
    rest = [x["close"] for x in g if x["day"] != best]
    if not rest or st.mean(rest) <= 0:
        miss.append("not positive without the best day")
    if sum(1 for v in days.values() if st.mean(v) > 0) < 0.6 * len(days):
        miss.append("under 60% of days positive")
    return "bar met" if not miss else "not yet: " + ", ".join(miss)


def write_summary(root: Path = ROOT) -> Path:
    rows = load(root)
    head = "| bucket | n | mean close % | up | hit +15% | stop first | days + |\n|---|---|---|---|---|---|---|"
    out = ["# Pivot-state / level-break review (research only)", "",
           f"{len(rows)} signals on {len({r['day'] for r in rows})} days. ATM option bought at the signal, held to close, hindsight, before costs.", ""]
    for d, lvl, through in (("BULLISH", "R1", THROUGH_CALL), ("BEARISH", "S1", THROUGH_PUT)):
        R = [r for r in rows if r["dir"] == d]
        out += [f"## {'Calls' if d == 'BULLISH' else 'Puts'} - by pivot zone at the signal", "", head]
        out += [_line(s, [r for r in R if r["state"] == s]) for s in ORDER]
        out += ["", f"### By time since the first close beyond {lvl}", "", head]
        for a, b, n in ((0, 15, "0-15 min"), (15, 45, "15-45 min"), (45, 9999, "45+ min")):
            out.append(_line(n, [r for r in R if r["since_break"] is not None and a <= r["since_break"] < b]))
        out.append(_line(f"not through {lvl}", [r for r in R if r["since_break"] is None]))
        out += ["", f"### Through {lvl}: what happened to the signal", "", head]
        for f in ("TRADED", "A_PLUS", "V2_BLOCKED"):
            out.append(_line(f, [r for r in R if r["state"] in through and r["fate"] == f]))
        for rule in SOFT:
            g = [r for r in R if r["state"] in through and r["rule"] == rule]
            if g:
                out.append(_line("A+ " + rule, g))
        out.append("")
    rel = [r for r in rows if r["dir"] == "BEARISH" and r["state"] in THROUGH_PUT and r["rule"] in SOFT]
    out += ["## Verdict - puts through S1 that A+ held back for a late/extension rule", "", _line("released puts", rel).replace("| released puts", "- released puts:"),
            "", f"**{verdict(rel)}**", ""]
    path = root / "data" / "shadow_rules" / "pivot_review.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    print(run(day) or "nothing to do (no candles / signals / previous session)")
    print(write_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
