"""Shadow test for the V2 gate's top-5 limit: what would pass if the limit were top-10?

Live trading is NOT affected. Each scan the scanner re-runs the V2 gate on the same candidates with a top-10 mover
ranking; any candidate that passes top-10 but not the live top-5 is logged once per day (first time seen) to
data/shadow_v2/<date>.csv. `report()` joins those signals with the nightly option returns (missed_option_returns) to compare,
per day and cumulatively, the extra top-10 passes against the live trades and the rest of the V2-blocked signals.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "shadow_v2"
FIELDS = ["scenario", "time", "symbol", "direction", "ltp", "top10_rank", "stage", "setup_family", "from_open_pct"]


def log_new(extra: Iterable[Any], shadow_rank: dict[str, Any], when: datetime, seen: set[tuple[str, str]],
            out_dir: Path = OUT, scenario: str = "top10") -> int:
    """Append candidates that pass top-10 but not top-5, once per symbol/direction per day. Returns rows written."""
    ranks: dict[tuple[str, str], tuple[int, float]] = {}
    for side, key in (("BULLISH", "top_up"), ("BEARISH", "top_down")):
        for row in shadow_rank.get(key, []) or []:
            ranks[(str(row.get("symbol")), side)] = (int(row.get("v2_rank") or 0), float(row.get("from_open_pct") or 0.0))
    rows = []
    for c in extra:
        key = (str(getattr(c, "symbol", "")).upper(), str(getattr(c, "direction", "")).upper())
        if not key[0] or key in seen:
            continue
        seen.add(key)
        rank, from_open = ranks.get(key, (0, 0.0))
        rows.append({"scenario": scenario, "time": when.strftime("%H:%M:%S"), "symbol": key[0], "direction": key[1],
                     "ltp": getattr(c, "ltp", ""), "top10_rank": rank, "stage": getattr(c, "stage", ""),
                     "setup_family": getattr(c, "setup_family", ""), "from_open_pct": from_open})
    if rows:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{when.date().isoformat()}.csv"
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            if new:
                writer.writeheader()
            writer.writerows(rows)
    return len(rows)


def _stats(values: list[float], best: list[float]) -> str:
    if not values:
        return "n=0"
    s = sorted(values)
    return (f"n={len(values)} | mean close {sum(values) / len(values):+.1f}% (about {sum(values) / len(values) - 1.5:+.1f}% after costs) | "
            f"median {s[len(s) // 2]:+.1f}% | winners {100 * sum(v > 0 for v in values) // len(values)}% | reached +30%: {sum(b >= 30 for b in best)}")


def report(root: Path = ROOT) -> Path | None:
    """Writes data/shadow_v2/summary.md comparing outcomes (ATM option, hindsight, entry at first-ready candle +1%)."""
    groups: dict[str, tuple[list[float], list[float]]] = {"extra": ([], []), "norank_only": ([], []), "other_v2_blocked": ([], []), "traded": ([], []),
                                                         "est_trend": ([], [])}
    per_day = []
    for csv_path in sorted((root / "data" / "shadow_v2").glob("20*.csv")):
        day = csv_path.stem
        returns = root / "data" / "missed_opportunities" / day / "option_returns.json"
        if not returns.exists():
            continue
        try:
            opts = {(r["symbol"], r["dir"]): r for r in json.loads(returns.read_text(encoding="utf-8")) if r["kind"] == "ATM"}
            logged = list(csv.DictReader(csv_path.open(encoding="utf-8")))
            extra = {(r["symbol"], r["direction"]) for r in logged if r.get("scenario", "top10") == "top10"}
            norank = {(r["symbol"], r["direction"]) for r in logged if r.get("scenario") == "norank"} - extra
            est = {(r["symbol"], r["direction"]) for r in logged if r.get("scenario") == "est_trend"}
        except (OSError, ValueError, KeyError):
            continue
        day_extra = ([], [])
        for key, r in opts.items():
            fate = str(r.get("fate", ""))
            if key in extra:
                group = "extra"
            elif key in norank:
                group = "norank_only"
            elif fate.startswith("V2_BLOCKED"):
                group = "other_v2_blocked"
            elif fate == "TRADED":
                group = "traded"
            else:
                continue
            groups[group][0].append(float(r["close"]))
            groups[group][1].append(float(r["best"]))
            if key in est and fate.startswith("V2_BLOCKED"):
                groups["est_trend"][0].append(float(r["close"]))
                groups["est_trend"][1].append(float(r["best"]))
            if group == "extra":
                day_extra[0].append(float(r["close"]))
                day_extra[1].append(float(r["best"]))
        per_day.append((day, day_extra))
    if not per_day:
        return None
    lines = ["# V2 top-10 shadow test", "",
             "Compares the signals that would pass if the V2 limit were top-10 (but not top-5) with the live trades and the other V2-blocked signals.",
             "Outcome = at-the-money option bought at the first-ready candle +1% and held to the close; hindsight, before real fills.", "",
             f"- **Extra top-10 passes:** {_stats(*groups['extra'])}",
             f"- **Extra with NO rank rule at all (beyond top-10):** {_stats(*groups['norank_only'])}",
             f"- **Established-trend setups V2 blocked (the proposed widening, before the 3-per-side cap):** {_stats(*groups['est_trend'])}",
             f"- **Other V2-blocked:** {_stats(*groups['other_v2_blocked'])}",
             f"- **Live trades:** {_stats(*groups['traded'])}", "", "| Day | Extra top-10 passes |", "|---|---|"]
    lines += [f"| {day} | {_stats(*vals)} |" for day, vals in per_day]
    out = root / "data" / "shadow_v2" / "summary.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
