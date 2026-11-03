"""Build leakage-aware research rows from clean 1-minute shadow sessions.

This prepares a dataset only. It does not train, score, import, or enable a
model in the scanner. Future outcomes are stored as targets, never features.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from shadow_1m_batch_evaluation import summarize_sessions


FEATURE_COLUMNS = (
    "side",
    "minute_of_day",
    "level_distance_pct",
    "volume_multiple",
    "close_location",
)
OUTCOME_COLUMNS = (
    "confirmed_within_6m",
    "confirmation_minute_of_day",
    "forward_best_pct",
    "forward_worst_pct",
)
CSV_COLUMNS = (
    "session_date", "symbol", "signal_minute_of_day", *FEATURE_COLUMNS,
    *OUTCOME_COLUMNS, "session_split",
)
MINIMUM_SESSIONS_FOR_SPLIT = 10


def chronological_splits(days: Iterable[str], *, minimum_sessions: int = MINIMUM_SESSIONS_FOR_SPLIT) -> dict[str, str]:
    """Assign whole sessions to chronological train/validation/test partitions.

    Fewer than ``minimum_sessions`` sessions receive no partition. This
    prevents a handful of days from being presented as a meaningful holdout.
    """
    ordered = sorted({date.fromisoformat(day).isoformat() for day in days})
    if len(ordered) < minimum_sessions:
        return {day: "unassigned_insufficient_sessions" for day in ordered}
    test_n = max(2, round(len(ordered) * 0.15))
    validation_n = max(1, round(len(ordered) * 0.15))
    train_n = len(ordered) - test_n - validation_n
    if train_n < 1:
        return {day: "unassigned_insufficient_sessions" for day in ordered}
    result: dict[str, str] = {}
    for day in ordered[:train_n]:
        result[day] = "train"
    for day in ordered[train_n:train_n + validation_n]:
        result[day] = "validation"
    for day in ordered[train_n + validation_n:]:
        result[day] = "untouched_test"
    return result


def build_dataset(sessions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build rows from broad-coverage, undamaged sessions only."""
    sessions = list(sessions)
    quality = summarize_sessions(sessions)
    accepted = {row["day"] for row in quality["sessions"] if row["clean_broad_coverage_session"]}
    splits = chronological_splits(accepted)
    rows: list[dict[str, Any]] = []
    for item in sessions:
        report = item["report"]
        day = date.fromisoformat(report["day"]).isoformat()
        if day not in accepted:
            continue
        for label in report.get("candidate_labels", []):
            minute = int(label["minute"])
            confirmation = label.get("confirmation_minute")
            rows.append({
                "session_date": day,
                "symbol": str(label["symbol"]).upper(),
                "signal_minute_of_day": minute,
                "side": label["side"],
                "minute_of_day": minute,
                "level_distance_pct": float(label["level_distance_pct"]),
                "volume_multiple": float(label["volume_multiple"]),
                "close_location": float(label["close_location"]),
                "confirmed_within_6m": int(bool(label["confirmed"])),
                "confirmation_minute_of_day": int(confirmation) if confirmation is not None else "",
                "forward_best_pct": label.get("forward_best_pct", "") if label.get("forward_best_pct") is not None else "",
                "forward_worst_pct": label.get("forward_worst_pct", "") if label.get("forward_worst_pct") is not None else "",
                "session_split": splits[day],
            })
    rows.sort(key=lambda row: (row["session_date"], row["signal_minute_of_day"], row["symbol"], row["side"]))
    return {
        "rows": rows,
        "manifest": {
            "research_only": True,
            "training_performed": False,
            "model_enabled": False,
            "session_count": len(accepted),
            "accepted_sessions": sorted(accepted),
            "row_count": len(rows),
            "feature_columns": list(FEATURE_COLUMNS),
            "outcome_columns_not_features": list(OUTCOME_COLUMNS),
            "grouping_columns_not_features": ["session_date", "symbol"],
            "chronological_split_policy": f"whole sessions; minimum {MINIMUM_SESSIONS_FOR_SPLIT} clean sessions",
            "splits": splits,
            "clean_session_policy": quality["clean_session_definition"],
            "label_definition": "observed level confirmation within 6 subsequent one-minute bars; forward best/worst underlying excursion over 12 bars after confirmation",
            "known_limitations": [
                "Only underlying-stock price outcomes are available; no candidate-specific option returns.",
                "The current clean sample is too small for train/validation/test assignment or model fitting.",
                "Features are limited to candidate-time side, time, level distance, relative volume, and candle close location.",
                "No VWAP, market regime, news, fees, fill model, or exit policy is represented.",
            ],
        },
    }


def _load_sessions(root: Path, days: list[str]) -> list[dict[str, Any]]:
    sessions = []
    for raw_day in days:
        day = date.fromisoformat(raw_day).isoformat()
        folder = root / "data" / "shadow_1m" / day
        report_name = "prebreakout_evaluation_v2.json" if day == "2026-10-28" else "prebreakout_evaluation.json"
        sessions.append({
            "report": json.loads((folder / report_name).read_text(encoding="utf-8")),
            "manifest": json.loads((folder / "manifest.json").read_text(encoding="utf-8")),
        })
    return sessions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("days", nargs="+", help="Session dates YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--write", action="store_true", help="Write a new CSV and JSON manifest; never overwrite")
    parser.add_argument("--output-prefix", type=Path, help="Output path without extension, used with --write")
    args = parser.parse_args()
    result = build_dataset(_load_sessions(args.root, args.days))
    if args.write:
        prefix = args.output_prefix or (args.root / "data" / "ml_shadow" / "prebreakout_dataset")
        prefix.parent.mkdir(parents=True, exist_ok=True)
        csv_path, manifest_path = prefix.with_suffix(".csv"), prefix.with_suffix(".json")
        if csv_path.exists() or manifest_path.exists():
            parser.error("output CSV or manifest already exists; refusing to overwrite")
        with csv_path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(result["rows"])
        with manifest_path.open("x", encoding="utf-8", newline="") as handle:
            json.dump(result["manifest"], handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"{csv_path}\n{manifest_path}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
