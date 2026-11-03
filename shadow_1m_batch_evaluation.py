"""Coverage-aware aggregation of saved one-minute shadow evaluations."""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping


def summarize_sessions(sessions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize per-session reports and pool only broad-coverage sessions.

    A broad-coverage session is explicitly defined as at least 200 symbols
    with valid 09:15 opening bars and at least 90% of the stock files in that
    day's collection manifest. This is a research reporting threshold, not a
    trading rule.
    """
    sessions = list(sessions)
    rows: list[dict[str, Any]] = []
    for item in sessions:
        report, manifest = item["report"], item["manifest"]
        counts, summary = report["counts"], report["summary"]
        collected = int(manifest.get("stocks", {}).get("files", 0) or 0)
        valid = int(counts.get("symbols_with_valid_opening_range", 0) or 0)
        coverage = valid / collected if collected else 0.0
        broad = valid >= 200 and coverage >= 0.90
        stock_meta = manifest.get("stocks", {})
        option_meta = manifest.get("options", {})
        damaged = int(stock_meta.get("damaged_files", 0) or 0) + int(option_meta.get("damaged_files", 0) or 0)
        invalid = int(stock_meta.get("invalid_rows", 0) or 0) + int(option_meta.get("invalid_rows", 0) or 0)
        clean = broad and damaged == 0 and invalid == 0
        rows.append({
            "day": report["day"],
            "collected_symbols": collected,
            "symbols_with_valid_opening_range": valid,
            "opening_coverage_pct": round(coverage * 100, 3),
            "broad_coverage_session": broad,
            "damaged_files": damaged,
            "invalid_rows": invalid,
            "clean_broad_coverage_session": clean,
            "candidates": int(counts.get("candidates", 0)),
            "eligible_candidates": int(counts.get("eligible_candidates", 0)),
            "confirmed": int(counts.get("confirmed", 0)),
            "confirmation_rate_pct": summary.get("confirmation_rate_pct"),
            "median_directional_best_pct": summary.get("median_directional_best_pct"),
            "median_directional_worst_pct": summary.get("median_directional_worst_pct"),
            "count_best_at_least_1pct": int(summary.get("count_best_at_least_1pct", 0)),
            "count_worst_at_or_below_minus_1pct": int(summary.get("count_worst_at_or_below_minus_1pct", 0)),
        })
    rows.sort(key=lambda row: row["day"])
    clean_days = {row["day"] for row in rows if row["clean_broad_coverage_session"]}
    # Caller provides raw evaluation records so pooled excursion stats are
    # reconstructed from confirmed outcomes, not averages of daily medians.
    raw = [item["report"] for item in sessions if item["report"]["day"] in clean_days]
    eligible = sum(int(r["counts"].get("eligible_candidates", 0)) for r in raw)
    confirmed = sum(int(r["counts"].get("confirmed", 0)) for r in raw)
    outcomes = [label for r in raw for label in r.get("candidate_labels", [])
                if label.get("confirmed") and label.get("forward_best_pct") is not None
                and label.get("forward_worst_pct") is not None]
    best = [float(label["forward_best_pct"]) for label in outcomes]
    worst = [float(label["forward_worst_pct"]) for label in outcomes]
    return {
        "research_only": True,
        "not_option_pnl_or_live_strategy_performance": True,
        "broad_coverage_definition": "at least 200 valid opening-range symbols and at least 90% of collected stock files",
        "clean_session_definition": "broad coverage plus zero damaged files and zero invalid rows across stock and option inputs",
        "sessions": rows,
        "clean_broad_coverage_pooled": {
            "session_count": len(raw),
            "days": sorted(clean_days),
            "eligible_candidates": eligible,
            "confirmed": confirmed,
            "confirmation_rate_pct": round(100 * confirmed / eligible, 3) if eligible else None,
            "confirmed_with_complete_outcomes": len(outcomes),
            "median_directional_best_pct": round(statistics.median(best), 6) if best else None,
            "median_directional_worst_pct": round(statistics.median(worst), 6) if worst else None,
            "count_best_at_least_1pct": sum(value >= 1.0 for value in best),
            "count_worst_at_or_below_minus_1pct": sum(value <= -1.0 for value in worst),
            "unique_confirmed_symbols": len({label["symbol"] for label in outcomes}),
        },
        "limitations": [
            "Multiple sessions are still a small sample and do not establish a trading edge.",
            "Price excursions are on the underlying stock, not option returns.",
            "No fees, slippage, fills, exit rules, VWAP, news, or market-index context are modeled.",
            "Partial-coverage days and sessions with damaged inputs are listed but excluded from the pooled summary.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("days", nargs="+", help="Session dates YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--write", action="store_true", help="Write a new JSON summary; never overwrite")
    parser.add_argument("--output", type=Path, help="Output path used with --write")
    args = parser.parse_args()
    sessions = []
    for day in args.days:
        date.fromisoformat(day)
        folder = args.root / "data" / "shadow_1m" / day
        report_path = folder / ("prebreakout_evaluation_v2.json" if day == "2026-10-28" else "prebreakout_evaluation.json")
        sessions.append({
            "report": json.loads(report_path.read_text(encoding="utf-8")),
            "manifest": json.loads((folder / "manifest.json").read_text(encoding="utf-8")),
        })
    encoded = json.dumps(summarize_sessions(sessions), indent=2, ensure_ascii=False) + "\n"
    if args.write:
        target = args.output or (args.root / "data" / "shadow_1m" / "batch_summary.json")
        with target.open("x", encoding="utf-8", newline="") as handle:
            handle.write(encoded)
        print(target)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
