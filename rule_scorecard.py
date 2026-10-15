"""Late-rule scorecard (SHADOW report, nothing trades).

For every signal the scanner saw reach ENTRY_READY, the nightly missed-opportunities job records what ATM option bought at that signal
would have done (best, worst and close, in % of premium; hindsight, before real fills). This scorecard groups those outcomes by

    the A+ rule that dropped the signal (late_10m_overheat, late_vwap_extension, overextended, pivot_to_r1, ...)  x  time of day

and sets them against the signals we actually traded, cumulatively over every day on file. It answers: "is this rule rejecting
signals that would have been as good as the ones we take?" - separately for the opening 30 minutes, where late/overheated moves
reverse, and for the rest of the day.

    data/shadow_rules/scorecard.md    human-readable, rewritten every night after the option returns are built
    data/shadow_rules/scorecard.json  the same numbers

    python rule_scorecard.py          rebuild now
"""

from __future__ import annotations

import glob
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
BUCKETS = ((0, 585, "before 09:45"), (585, 630, "09:45-10:30"), (630, 720, "10:30-12:00"), (720, 1440, "after 12:00"))
MIN_N = 8


def _mins(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return -1


def load_rows(root: Path = ROOT, first_day: str = "2026-10-01") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(root / "data" / "missed_opportunities" / "20*" / "option_returns.json"))):
        day = Path(path).parent.name
        if day < first_day:
            continue
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in data:
            if r.get("kind") != "ATM":
                continue
            fate = str(r.get("fate") or "")
            group = "TRADED" if fate == "TRADED" else ("V2_BLOCKED" if fate.startswith("V2_BLOCKED") else
                                                        fate.replace("A_PLUS:", "") if fate.startswith("A_PLUS") else None)
            if group is None:
                continue
            rows.append({"day": day, "group": group, "ready": _mins(r.get("ready", "")), "best": float(r.get("best") or 0),
                         "worst": float(r.get("worst") or 0), "close": float(r.get("close") or 0)})
    return rows


def _stats(g: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(g)
    days = defaultdict(list)
    for r in g:
        days[r["day"]].append(r["close"])
    return {"n": n, "days": len(days), "reach15": round(100 * sum(r["best"] >= 15 for r in g) / n),
            "reach30": round(100 * sum(r["best"] >= 30 for r in g) / n), "win": round(100 * sum(r["close"] > 0 for r in g) / n),
            "median_best": round(st.median(r["best"] for r in g)), "median_worst": round(st.median(r["worst"] for r in g)),
            "median_close": round(st.median(r["close"] for r in g)), "mean_close": round(st.mean(r["close"] for r in g), 1),
            "days_positive": sum(1 for v in days.values() if st.mean(v) > 0)}


def build(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    out: dict[str, Any] = {"days": sorted({r["day"] for r in rows}), "groups": {}}
    for group in sorted({r["group"] for r in rows}):
        g = [r for r in rows if r["group"] == group]
        entry = {"all": _stats(g) if g else None, "buckets": {}}
        for lo, hi, label in BUCKETS:
            b = [r for r in g if lo <= r["ready"] < hi]
            if b:
                entry["buckets"][label] = _stats(b)
        out["groups"][group] = entry
    return out


def _fmt(s: dict[str, Any]) -> str:
    return (f"{s['n']} | {s['reach15']}% | {s['reach30']}% | {s['median_best']:+d}% | {s['median_worst']:+d}% | "
            f"{s['median_close']:+d}% | {s['mean_close']:+.1f}% | {s['win']}% | {s['days_positive']}/{s['days']}")


def render(card: dict[str, Any]) -> str:
    days = card["days"]
    out = ["# Late-rule scorecard (shadow)", "",
           f"{len(days)} days on file ({days[0] if days else '-'} to {days[-1] if days else '-'}). ATM option bought at the first ENTRY_READY "
           "candle, hindsight, % of premium, before real fills and costs. Rows with fewer than "
           f"{MIN_N} signals are shown but should not be trusted.", "",
           "Columns: signals | reached +15% | reached +30% | median best | median worst | median close | mean close | closed up | days positive",
           ""]
    traded = card["groups"].get("TRADED", {})
    for label in [b[2] for b in BUCKETS]:
        out += [f"## {label}", "", "| Group | n | +15% | +30% | best | worst | close | mean | up | days+ |", "|---|---|---|---|---|---|---|---|---|---|"]
        order = ["TRADED", "V2_BLOCKED"] + sorted(g for g in card["groups"] if g not in ("TRADED", "V2_BLOCKED"))
        for g in order:
            s = card["groups"].get(g, {}).get("buckets", {}).get(label)
            if s:
                flag = "" if s["n"] >= MIN_N else " (few)"
                out.append(f"| {g}{flag} | " + _fmt(s).replace(" | ", " | ") + " |")
        base = traded.get("buckets", {}).get(label)
        if base and base["n"] >= MIN_N:
            better = [g for g, v in card["groups"].items() if g not in ("TRADED", "V2_BLOCKED")
                      and v["buckets"].get(label) and v["buckets"][label]["n"] >= MIN_N
                      and v["buckets"][label]["mean_close"] >= base["mean_close"] and v["buckets"][label]["reach15"] >= base["reach15"]]
            if better:
                out += ["", f"Rules rejecting signals at least as good as the traded ones in this window (mean close and +15% hit rate): "
                        + ", ".join(f"**{g}**" for g in better)]
        out.append("")
    out += ["_Watch the rows that stay at or above TRADED for several days and have 8+ signals; that is when a rule is a candidate to relax. "
            "Nothing here changes trading._", ""]
    return "\n".join(out)


def write(root: Path = ROOT) -> Path | None:
    rows = load_rows(root)
    if not rows:
        return None
    card = build(rows)
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scorecard.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
    path = folder / "scorecard.md"
    path.write_text(render(card), encoding="utf-8")
    return path


def main() -> int:
    p = write()
    print(p or "no option returns on file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
