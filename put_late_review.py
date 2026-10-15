"""Standing shadow test: should the A+ "late" rules be relaxed for PUTS between 10:00 and 13:00? (research only - changes nothing)

The candidate rule: for a bearish signal that A+ held back for `late_vwap_extension`, `late_10m_overheat` or `overextended`, let it
through when it appears between 10:00 and 13:00. `pivot_to_r1` stays blocking (it was clearly right on both sides).

Every night this file rebuilds data/shadow_rules/put_late_review.md from all days on file (ATM option bought at the signal, held to
close, hindsight, before costs) and prints a plain verdict against a fixed bar:

    at least 30 released signals across at least 5 days
    AND mean close positive and above the traded puts' mean minus 5 points
    AND at least 60% of the days positive
    AND still positive after removing the single best day
Anything less is reported as "not yet" with what is missing.

    python put_late_review.py
"""

from __future__ import annotations

import glob
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
FIRST_DAY = "2026-10-01"
SOFT = ("late_vwap_extension", "late_10m_overheat", "overextended")
WINDOW = (600, 780)                       # 10:00 - 13:00
MIN_SIGNALS, MIN_DAYS = 30, 5


def _mins(h: Any) -> int:
    a, b = str(h).split(":")[:2]
    return int(a) * 60 + int(b)


def load(root: Path = ROOT, first_day: str = FIRST_DAY) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "missed_opportunities" / "20*" / "option_returns.json"))):
        day = Path(p).parent.name
        if day < first_day:
            continue
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in data:
            if r.get("kind") != "ATM" or r.get("dir") != "BEARISH":
                continue
            try:
                t = _mins(r["ready"])
            except ValueError:
                continue
            fate = str(r.get("fate") or "")
            rule = fate.split(":", 1)[1] if fate.startswith("A_PLUS:") else ""
            rows.append({"day": day, "symbol": r["symbol"], "minute": t, "ready": r["ready"], "fate": fate, "rule": rule,
                         "best": float(r.get("best") or 0), "worst": float(r.get("worst") or 0), "close": float(r.get("close") or 0),
                         "stop_first": bool(r.get("stop_first"))})
    return rows


def _stats(g: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(g)
    if not n:
        return {"n": 0}
    days = defaultdict(list)
    for x in g:
        days[x["day"]].append(x["close"])
    return {"n": n, "days": len(days), "up": round(100 * sum(x["close"] > 0 for x in g) / n), "r15": round(100 * sum(x["best"] >= 15 for x in g) / n),
            "r30": round(100 * sum(x["best"] >= 30 for x in g) / n), "sf": round(100 * sum(x["stop_first"] for x in g) / n),
            "mean": round(st.mean(x["close"] for x in g), 1), "pos_days": sum(1 for v in days.values() if st.mean(v) > 0),
            "by_day": {d: (len(v), round(st.mean(v), 1)) for d, v in sorted(days.items())}}


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    released = [r for r in rows if r["rule"] in SOFT and WINDOW[0] <= r["minute"] < WINDOW[1]]
    held = [r for r in rows if r["rule"] in SOFT and not (WINDOW[0] <= r["minute"] < WINDOW[1])]
    pivot = [r for r in rows if r["rule"] == "pivot_to_r1" and WINDOW[0] <= r["minute"] < WINDOW[1]]
    traded = [r for r in rows if r["fate"] == "TRADED"]
    rel = _stats(released)
    out: dict[str, Any] = {"released": rel, "held_other_times": _stats(held), "pivot_control": _stats(pivot), "traded_puts": _stats(traded)}
    missing = []
    if rel["n"] < MIN_SIGNALS:
        missing.append(f"{rel['n']} of {MIN_SIGNALS} signals")
    if rel.get("days", 0) < MIN_DAYS:
        missing.append(f"{rel.get('days', 0)} of {MIN_DAYS} days")
    if rel["n"]:
        base = out["traded_puts"].get("mean", 0.0) if out["traded_puts"]["n"] else 0.0
        if rel["mean"] <= 0 or rel["mean"] < base - 5:
            missing.append(f"mean close {rel['mean']:+.1f}% is not positive and close to the traded puts ({base:+.1f}%)")
        if rel["pos_days"] / max(1, rel["days"]) < 0.6:
            missing.append(f"only {rel['pos_days']} of {rel['days']} days positive")
        if rel["days"] >= 2:
            best_day = max(rel["by_day"], key=lambda d: rel["by_day"][d][0] * rel["by_day"][d][1])
            rest = [x for x in released if x["day"] != best_day]
            if rest and st.mean(x["close"] for x in rest) <= 0:
                missing.append(f"not positive after removing {best_day}")
    out["missing"] = missing
    out["verdict"] = "supports relaxing" if rel["n"] and not missing else "not yet"
    return out


def render(ev: dict[str, Any], days: list[str]) -> str:
    def row(label: str, s: dict[str, Any]) -> str:
        if not s.get("n"):
            return f"| {label} | 0 | - | - | - | - | - | - |"
        return f"| {label} | {s['n']} | {s['days']} | {s['up']}% | {s['r15']}% | {s['r30']}% | {s['sf']}% | {s['mean']:+.1f}% |"
    out = ["# Put side: relax the A+ late rules between 10:00 and 13:00? (shadow)", "",
           f"{len(days)} day(s) on file. ATM option bought at the signal, held to close, hindsight, before costs.", "",
           "| Group | Signals | Days | Closed up | +15% | +30% | Stop first | Mean close |", "|---|---|---|---|---|---|---|---|",
           row("**RELEASED**: put held by late_vwap_extension / late_10m_overheat / overextended, 10:00-13:00", ev["released"]),
           row("Same rules, other times (stay blocked)", ev["held_other_times"]),
           row("Control: pivot_to_r1 on puts, 10:00-13:00 (stays blocked)", ev["pivot_control"]),
           row("Traded puts (reference)", ev["traded_puts"]), "",
           f"**Verdict: {ev['verdict']}.**" + ("" if not ev["missing"] else " Missing: " + "; ".join(ev["missing"]) + ".")]
    by = ev["released"].get("by_day") or {}
    if by:
        out += ["", "## Released group by day", "", "| Day | Signals | Mean close |", "|---|---|---|"]
        out += [f"| {d} | {n} | {m:+.1f}% |" for d, (n, m) in by.items()]
    out += ["", "_Research only. Bar: 30+ signals on 5+ days, positive and near the traded puts' mean, 60%+ of days positive, still positive "
            "without the best day. It is a prompt for a decision, not a decision._", ""]
    return "\n".join(out)


def write(root: Path = ROOT) -> Path | None:
    rows = load(root)
    if not rows:
        return None
    ev = evaluate(rows)
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "put_late_review.md"
    path.write_text(render(ev, sorted({r["day"] for r in rows})), encoding="utf-8")
    return path


def main() -> int:
    p = write()
    print(p.read_text(encoding="utf-8") if p else "no option returns on file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
