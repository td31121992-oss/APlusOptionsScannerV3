"""Cumulative review of the intraday scans that were true at entry (research only - changes nothing).

Reads every paper trade on file since the scan names started being recorded and, for each scan (and for the two groups that matter
most: "open at the day's extreme" and "a multi-day level already broken"), shows trades, winners, net rupees and how often the
option later reached +15%.

    python scan_review.py [first_day]       writes data/shadow_rules/scan_review.md and prints it

The nightly job calls this after the key-level report. Small counts mean nothing: look for a scan that stays on one side across days.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
FIRST_DAY = "2026-10-16"             # the first session the scan names are recorded
MIN_N = 8


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _truthy(v: Any) -> bool:
    return str(v).lower() in ("true", "1")


def load(root: Path = ROOT, first_day: str = FIRST_DAY) -> list[dict[str, Any]]:
    import trade_journal

    return [t for t in trade_journal.payload("", "", root)["trades"] if str(t.get("day")) >= first_day]


def _row_stats(g: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(g)
    return {"n": n, "days": len({t.get("day") for t in g}), "winners": sum(1 for t in g if _f(t.get("net")) > 0),
            "net": round(sum(_f(t.get("net")) for t in g)),
            "mfe15": sum(1 for t in g if _f(t.get("mfe_pct")) >= 15), "stopped": sum(1 for t in g if "STOP" in str(t.get("exit_reason")))}


def summarize(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ts = [t for t in trades if t.get("tr_scans_names") is not None]
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in ts:
        for name in str(t.get("tr_scans_names") or "").split("|"):
            if name:
                by[name].append(t)
    groups = {
        "Open at the day's extreme (Open = Low / High)": [t for t in ts if _truthy(t.get("tr_open_ext"))],
        "Not at the open's extreme": [t for t in ts if not _truthy(t.get("tr_open_ext"))],
        "A 5/10/30/90-day level already broken": [t for t in ts if _truthy(t.get("tr_multi_day"))],
        "No multi-day level broken": [t for t in ts if not _truthy(t.get("tr_multi_day"))],
    }
    return {"trades": len(ts), "days": sorted({str(t.get("day")) for t in ts}),
            "scans": {k: _row_stats(v) for k, v in by.items()}, "groups": {k: _row_stats(v) for k, v in groups.items() if v}}


def render(s: dict[str, Any]) -> str:
    out = ["# Intraday scans true at entry (shadow)", ""]
    if not s["trades"]:
        return "\n".join(out + ["No trades with scan names on file yet (they are recorded from 16 Oct 2026).", ""])
    d = s["days"]
    out += [f"{s['trades']} trades over {len(d)} day(s) ({d[0]} to {d[-1]}). 'Reached +15%' = the option's peak was at least 15% above entry. "
            f"Rows under {MIN_N} trades are shown but mean little.", "",
            "## Groups", "", "| Group | Trades | Winners | Reached +15% | Stopped | Net Rs |", "|---|---|---|---|---|---|"]
    for k, v in s["groups"].items():
        out.append(f"| {k} | {v['n']} | {v['winners']} | {v['mfe15']} | {v['stopped']} | {v['net']:+,} |")
    out += ["", "## Each scan", "", "| Scan at entry | Trades | Days | Winners | Reached +15% | Stopped | Net Rs |", "|---|---|---|---|---|---|---|"]
    for k, v in sorted(s["scans"].items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        flag = "" if v["n"] >= MIN_N else " (few)"
        out.append(f"| {k}{flag} | {v['n']} | {v['days']} | {v['winners']} | {v['mfe15']} | {v['stopped']} | {v['net']:+,} |")
    out += ["", "_Research only. On 15 Oct (before these tags) the open at the day's extreme appeared on 3 of 4 winners and 2 of 11 losers, "
            "and a 5 or 10-day breakout already done on 0 of 4 winners and 7 of 11 losers; across 948 past signals only the open-at-the-extreme "
            "effect could be confirmed. This table is how the multi-day finding gets tested._", ""]
    return "\n".join(out)


def write(root: Path = ROOT, first_day: str = FIRST_DAY) -> Path:
    s = summarize(load(root, first_day))
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "scan_review.md"
    path.write_text(render(s), encoding="utf-8")
    return path


def main() -> int:
    first = sys.argv[1] if len(sys.argv) > 1 else FIRST_DAY
    print(write(ROOT, first).read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
