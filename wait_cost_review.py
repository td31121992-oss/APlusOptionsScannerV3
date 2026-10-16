"""What do the waits cost, and which wait costs the most? (research only; changes nothing)

Traded signals were first flagged a median 10 minutes before the real entry, and an entry at the first flag would have closed about 5 points better (early_entry_review.py).
This splits that delay by the wait that caused it, from the per-signal snapshots the scanner writes (data/signal_snapshots/<day>.csv, from the first session after the
16 Oct 2026 restart). For every trade: the status the signal was in from its first sighting to the entry -

    a_plus    an A+ rule held it back (the rule name is kept: late_vwap_extension, late_10m_overheat, pivot_to_r1, ...)
    v2        Stock Selection V2 blocked it (not in the top N, current 5-minute reversal, no fresh continuation, ...)
    passed    all gates passed but the entry had not happened yet (option selection, safety checks, pacing)
    other     anything else

Cost: the early-entry gap (option close from the first flag minus from the real entry, in points) is shared out in proportion to the time spent in each status.
That is an allocation, not a counterfactual, so it ranks the waits; it does not prove what removing one would do.
Benefit (the other side): signals each wait held back that never traded, and what their options did (data/missed_opportunities/<day>/option_returns.json).

    data/shadow_rules/wait_cost/<day>.csv       data/shadow_rules/wait_cost.md

    python wait_cost_review.py [YYYY-MM-DD ...]
"""

from __future__ import annotations

import csv
import glob
import json
import statistics as st
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import early_entry_review as eer

ROOT = Path(__file__).resolve().parent
CATS = ("a_plus", "v2", "passed", "other")
FIELDS = ["day", "symbol", "dir", "first_seen", "entry_time", "delay_min", "a_plus_min", "v2_min", "passed_min", "other_min", "a_plus_rules", "v2_reasons", "gap_points",
          "cost_a_plus", "cost_v2", "cost_passed", "cost_other"]


def category(status: str) -> str:
    s = str(status or "").upper()
    if s.startswith("A_PLUS"):
        return "a_plus"
    if "V2" in s:
        return "v2"
    if s.startswith("PASSED"):
        return "passed"
    return "other"


def _t(v: str) -> datetime:
    return datetime.fromisoformat(str(v))


def timeline(snapshots: list[dict[str, Any]], entry: datetime) -> dict[str, Any] | None:
    """Minutes spent in each category from the first sighting to the entry, and the A+ rules / V2 reasons involved. Rows are one per status change (or every 5 minutes)."""
    rows = sorted((r for r in snapshots if _naive(_t(r["time"])) <= _naive(entry)), key=lambda r: r["time"])
    if not rows:
        return None
    mins: Counter = Counter()
    rules: Counter = Counter()
    v2r: Counter = Counter()
    for i, r in enumerate(rows):
        end = _naive(_t(rows[i + 1]["time"])) if i + 1 < len(rows) else _naive(entry)
        d = max(0.0, (end - _naive(_t(r["time"]))).total_seconds() / 60.0)
        c = category(r["status"])
        mins[c] += d
        if c == "a_plus":
            rules[str(r["status"]).upper().replace("A_PLUS_WAIT_", "").lower()] += d
        elif c == "v2":
            for part in str(r.get("reasons") or "").replace("Stock Selection V2 blocked:", "").split(";"):
                part = part.strip().split("(")[0].strip()
                if part:
                    v2r[part.lower()[:40]] += d
    total = sum(mins.values())
    return {"first_seen": rows[0]["time"], "delay_min": round((_naive(entry) - _naive(_t(rows[0]["time"]))).total_seconds() / 60.0, 1), "mins": {c: round(mins[c], 1) for c in CATS},
            "total": total, "rules": rules, "v2": v2r}


def _naive(x: datetime) -> datetime:
    return x.replace(tzinfo=None)


def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def run(day: str, root: Path = ROOT) -> Path | None:
    snap = root / "data" / "signal_snapshots" / f"{day}.csv"
    if not snap.exists():
        return None
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    with snap.open(encoding="utf-8", newline="") as h:
        for r in csv.DictReader(h):
            by_key[(r["symbol"], r["direction"])].append(r)
    gaps: dict[tuple[str, str], float] = {}
    ee = root / "data" / "shadow_rules" / "early_entry" / f"{day}.csv"
    if ee.exists():
        with ee.open(encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                a, b = _num(r.get("flag_close")), _num(r.get("act_close"))
                if a is not None and b is not None:
                    gaps[(r["symbol"], r["dir"])] = a - b
    rows = []
    for t in eer.trades_for(day, root):
        d = "BULLISH" if str(t.get("option_type")).upper() == "CE" else "BEARISH"
        tl = timeline(by_key.get((t["symbol"], d), []), _t(t["entry_time"]))
        if not tl:
            continue
        gap = gaps.get((t["symbol"], d))
        tot = tl["total"] or 1.0
        row = {"day": day, "symbol": t["symbol"], "dir": d, "first_seen": tl["first_seen"][11:16], "entry_time": str(t["entry_time"])[11:16], "delay_min": tl["delay_min"],
               "a_plus_min": tl["mins"]["a_plus"], "v2_min": tl["mins"]["v2"], "passed_min": tl["mins"]["passed"], "other_min": tl["mins"]["other"],
               "a_plus_rules": "|".join(f"{k}:{v:.0f}" for k, v in tl["rules"].most_common(4)), "v2_reasons": "|".join(f"{k}:{v:.0f}" for k, v in tl["v2"].most_common(4)),
               "gap_points": "" if gap is None else round(gap, 1)}
        for c in CATS:
            row[f"cost_{c}"] = "" if gap is None else round(gap * tl["mins"][c] / tot, 2)
        rows.append(row)
    folder = root / "data" / "shadow_rules" / "wait_cost"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    write_summary(root)
    return path


def _benefit(root: Path) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for p in sorted(glob.glob(str(root / "data" / "missed_opportunities" / "20*" / "option_returns.json"))):
        if Path(p).parent.name < "2026-10-19":
            continue
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in data:
            f = str(r.get("fate") or "")
            if r.get("kind") != "ATM" or f in ("TRADED", "") or r.get("close") is None:
                continue
            key = "V2" if f.startswith("V2") else ("A+ " + f.split(":", 1)[1] if f.startswith("A_PLUS:") else None)
            if key:
                out[key].append(float(r["close"]))
    return out


def write_summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "wait_cost" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    n = len(rows)
    days = sorted({r["day"] for r in rows})
    delay = [_num(r["delay_min"]) or 0.0 for r in rows]
    out = ["# What the waits cost (research only)", "",
           f"{n} traded signals on {len(days)} day(s) ({days[0]} to {days[-1]}). First sighting to entry: median {st.median(delay):.0f} min, mean {st.mean(delay):.0f} min.", "",
           "| Wait | Mean minutes per trade | Share of the delay | Cost allocated (points of option close, mean per trade) |", "|---|---|---|---|"]
    tot_min = sum(sum(_num(r[f"{c}_min"]) or 0.0 for c in CATS) for r in rows) or 1.0
    for c, label in (("a_plus", "A+ rules"), ("v2", "V2 stock selection"), ("passed", "Gates passed, entry pending"), ("other", "Other")):
        m = [_num(r[f"{c}_min"]) or 0.0 for r in rows]
        cost = [x for x in (_num(r[f"cost_{c}"]) for r in rows) if x is not None]
        out.append(f"| {label} | {st.mean(m):.1f} | {100 * sum(m) / tot_min:.0f}% | {(f'{st.mean(cost):+.2f}' if cost else '-')} |")
    rules: Counter = Counter()
    v2: Counter = Counter()
    for r in rows:
        for part in str(r.get("a_plus_rules") or "").split("|"):
            if ":" in part:
                k, v = part.rsplit(":", 1)
                rules[k] += float(v)
        for part in str(r.get("v2_reasons") or "").split("|"):
            if ":" in part:
                k, v = part.rsplit(":", 1)
                v2[k] += float(v)
    if rules:
        out += ["", "A+ rules by minutes of waiting: " + ", ".join(f"{k} {v:.0f}" for k, v in rules.most_common(6)) + "."]
    if v2:
        out += ["", "V2 reasons by minutes of waiting: " + ", ".join(f"{k} {v:.0f}" for k, v in v2.most_common(6)) + "."]
    ben = _benefit(root)
    if ben:
        out += ["", "## The other side: signals each wait held back that never traded (ATM option held to close)", "", "| Held back by | Signals | Mean close | Closed up |", "|---|---|---|---|"]
        for k, v in sorted(ben.items(), key=lambda kv: -len(kv[1]))[:10]:
            out.append(f"| {k} | {len(v)} | {st.mean(v):+.1f}% | {100 * sum(x > 0 for x in v) / len(v):.0f}% |")
        out.append("")
    worst = max(("a_plus", "v2", "passed"), key=lambda c: sum(_num(r[f"{c}_min"]) or 0.0 for r in rows))
    out += ["", f"Longest total wait: **{ {'a_plus': 'A+ rules', 'v2': 'V2 stock selection', 'passed': 'gates passed, entry pending'}[worst] }**.",
            "", "_The cost is the early-entry gap shared out by time, so it ranks the waits; it is not a counterfactual. Research only._", ""]
    path = root / "data" / "shadow_rules" / "wait_cost.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    import sys

    for d in sys.argv[1:] or [date.today().isoformat()]:
        print(d, run(d), flush=True)
    print(write_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
