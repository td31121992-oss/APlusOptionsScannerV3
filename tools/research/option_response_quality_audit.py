#!/usr/bin/env python3
"""Read-only quality audit for APlus option-response shadow CSVs.

This tool reads the output of the local option-response shadow study and writes
an audit JSON beside it (or to --output). It never edits input data, ledgers,
scanner rules, or trade records.

Example:
  python tools/research/option_response_quality_audit.py
  python tools/research/option_response_quality_audit.py --input path/to/option_response_observations.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path(
    "data/option_response_shadow_20261026/option_response_observations.csv"
)
REQUIRED = {
    "day", "symbol", "direction", "kind", "strike", "expiry",
    "option_security_id", "ready", "entry_snapshot", "target_minutes",
    "exit_snapshot", "snapshot_delay_minutes", "underlying_entry_spot",
    "underlying_later_spot", "direction_adjusted_underlying_move_pct",
    "entry_ask", "entry_ltp", "exit_bid", "exit_ltp",
    "option_return_ask_to_bid_pct", "option_return_ltp_to_ltp_pct",
    "report_entry_price", "report_entry_vs_chain_ask_pct", "quote_method",
}
NUMERIC = {
    "snapshot_delay_minutes", "underlying_entry_spot", "underlying_later_spot",
    "direction_adjusted_underlying_move_pct", "entry_ask", "entry_ltp",
    "exit_bid", "exit_ltp", "option_return_ask_to_bid_pct",
    "option_return_ltp_to_ltp_pct", "report_entry_price",
    "report_entry_vs_chain_ask_pct",
}


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def median(values: list[float]) -> float | None:
    values = [x for x in values if math.isfinite(x)]
    return round(statistics.median(values), 4) if values else None


def percent(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return (numerator / denominator - 1.0) * 100.0


def distribution(values: list[float]) -> dict[str, Any]:
    values = [x for x in values if math.isfinite(x)]
    if not values:
        return {"n": 0, "min": None, "median": None, "p90": None, "max": None}
    ordered = sorted(values)
    p90_index = min(len(ordered) - 1, math.ceil(0.90 * len(ordered)) - 1)
    return {
        "n": len(ordered),
        "min": round(ordered[0], 4),
        "median": round(statistics.median(ordered), 4),
        "p90": round(ordered[p90_index], 4),
        "max": round(ordered[-1], 4),
    }


def key_for(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(str(row.get(k, "")).strip() for k in (
        "day", "symbol", "direction", "kind", "strike", "expiry",
        "option_security_id", "ready", "target_minutes",
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    input_path = args.input
    if not input_path.is_file():
        parser.error(f"Input CSV not found: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        rows = list(reader)

    missing_columns = sorted(REQUIRED - headers)
    optional_fields = {
        "entry_bid": "Required to calculate actual entry bid-ask spread",
        "entry_theta": "Useful metadata; not a causal measure of realised theta",
        "entry_iv": "Needed for IV-change diagnostics",
        "exit_iv": "Needed for IV-change diagnostics",
        "entry_delta": "Useful for delta-adjusted response analysis",
    }
    missing_optional = {
        name: reason for name, reason in optional_fields.items() if name not in headers
    }

    for row in rows:
        row["_numeric"] = {name: number(row.get(name)) for name in NUMERIC}

    delays = [r["_numeric"]["snapshot_delay_minutes"] for r in rows]
    delays = [x for x in delays if x is not None]
    entry_diff = [
        abs(r["_numeric"]["report_entry_vs_chain_ask_pct"])
        for r in rows if r["_numeric"]["report_entry_vs_chain_ask_pct"] is not None
    ]
    quote_method = Counter(r.get("quote_method", "") for r in rows)
    horizons = Counter(r.get("target_minutes", "") for r in rows)
    dates = Counter(r.get("day", "") for r in rows)
    kinds = Counter(r.get("kind", "") for r in rows)

    keys = [key_for(r) for r in rows]
    duplicate_count = len(keys) - len(set(keys))
    unique_signals = {
        tuple(str(r.get(k, "")).strip() for k in (
            "day", "symbol", "direction", "kind", "strike", "expiry",
            "option_security_id", "ready",
        ))
        for r in rows
    }

    entry_ask_ltp_diff = []
    missing_or_invalid_entry_quote = 0
    missing_or_invalid_exit_quote = 0
    ask_below_ltp = 0
    bid_above_ltp = 0
    for row in rows:
        n = row["_numeric"]
        if not n["entry_ask"] or n["entry_ask"] <= 0:
            missing_or_invalid_entry_quote += 1
        if not n["exit_bid"] or n["exit_bid"] <= 0:
            missing_or_invalid_exit_quote += 1
        if n["entry_ask"] and n["entry_ltp"] and n["entry_ltp"] > 0:
            entry_ask_ltp_diff.append(percent(n["entry_ask"], n["entry_ltp"]))
            if n["entry_ask"] < n["entry_ltp"]:
                ask_below_ltp += 1
        if n["exit_bid"] and n["exit_ltp"] and n["exit_ltp"] > 0:
            if n["exit_bid"] > n["exit_ltp"]:
                bid_above_ltp += 1

    horizon_report: dict[str, Any] = {}
    for horizon in sorted(horizons, key=lambda x: number(x) or 0):
        group = [r for r in rows if r.get("target_minutes", "") == horizon]
        local_delays = [
            r["_numeric"]["snapshot_delay_minutes"] for r in group
            if r["_numeric"]["snapshot_delay_minutes"] is not None
        ]
        ask_bid_returns = [
            r["_numeric"]["option_return_ask_to_bid_pct"] for r in group
            if r["_numeric"]["option_return_ask_to_bid_pct"] is not None
        ]
        underlying_moves = [
            r["_numeric"]["direction_adjusted_underlying_move_pct"] for r in group
            if r["_numeric"]["direction_adjusted_underlying_move_pct"] is not None
        ]
        horizon_report[horizon] = {
            "rows": len(group),
            "snapshot_delay_minutes": distribution(local_delays),
            "delay_over_3_minutes": sum(x > 3 for x in local_delays),
            "delay_over_5_minutes": sum(x > 5 for x in local_delays),
            "ask_to_bid_return_pct": distribution(ask_bid_returns),
            "positive_return_pct": round(
                100 * sum(x > 0 for x in ask_bid_returns) / len(ask_bid_returns), 2
            ) if ask_bid_returns else None,
            "direction_adjusted_underlying_move_pct": distribution(underlying_moves),
        }

    day_horizon = {}
    for day in sorted(dates):
        day_horizon[day] = {}
        for horizon in sorted(horizons, key=lambda x: number(x) or 0):
            group = [r for r in rows if r.get("day") == day and r.get("target_minutes") == horizon]
            returns = [
                r["_numeric"]["option_return_ask_to_bid_pct"] for r in group
                if r["_numeric"]["option_return_ask_to_bid_pct"] is not None
            ]
            day_horizon[day][horizon] = {
                "n": len(group),
                "median_ask_to_bid_return_pct": median(returns),
                "positive_return_pct": round(
                    100 * sum(x > 0 for x in returns) / len(returns), 2
                ) if returns else None,
            }

    warnings = []
    if missing_columns:
        warnings.append("Required columns are missing; some checks are incomplete.")
    if "entry_bid" not in headers:
        warnings.append(
            "Input has no entry_bid. The true entry bid-ask spread cannot be calculated; "
            "entry ask versus LTP is not a substitute for the bid-ask spread."
        )
    if duplicate_count:
        warnings.append("Duplicate observation keys exist; investigate before aggregating.")
    if entry_diff and sum(x > 10 for x in entry_diff) / len(entry_diff) > 0.10:
        warnings.append(
            "More than 10% of comparable report-entry/chain-ask differences exceed 10%; "
            "contract or timing alignment needs review."
        )
    if delays and sum(x > 5 for x in delays) / len(delays) > 0.05:
        warnings.append(
            "More than 5% of horizon observations are over five minutes late; "
            "avoid treating nominal horizons as exact."
        )
    if len(dates) < 10:
        warnings.append(
            "Fewer than ten trading dates are present; findings are exploratory, not a production rule."
        )

    report = {
        "mode": "SHADOW_ONLY_READ_ONLY",
        "input_file": str(input_path),
        "rows": len(rows),
        "columns_missing": missing_columns,
        "optional_fields_missing": missing_optional,
        "dates": dict(dates),
        "horizons": dict(horizons),
        "option_kinds": dict(kinds),
        "quote_methods": dict(quote_method),
        "unique_signal_contracts": len(unique_signals),
        "duplicate_observation_keys": duplicate_count,
        "snapshot_delay_minutes": distribution(delays),
        "report_entry_vs_chain_ask_absolute_difference_pct": distribution(entry_diff),
        "entry_ask_vs_ltp_difference_pct": distribution(entry_ask_ltp_diff),
        "entry_ask_below_ltp_rows": ask_below_ltp,
        "exit_bid_above_ltp_rows": bid_above_ltp,
        "missing_or_invalid_entry_ask_rows": missing_or_invalid_entry_quote,
        "missing_or_invalid_exit_bid_rows": missing_or_invalid_exit_quote,
        "horizon_results": horizon_report,
        "per_day_per_horizon": day_horizon,
        "warnings": warnings,
        "limitations": [
            "This is a data-quality audit, not a profitability test.",
            "The underlying input matches symbol, strike, side and selected expiry; it may not prove the original report contract.",
            "Entry ask versus LTP is not an actual execution fill.",
            "Without entry bid, the true entry spread is unavailable.",
            "Premium changes cannot be attributed to theta alone without controlling for underlying movement, IV and quote quality.",
            "No scanner rules, paper-trade ledgers, or existing input files are modified.",
        ],
    }

    output_path = args.output or input_path.with_name("option_response_quality_audit.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("===== OPTION RESPONSE DATA QUALITY AUDIT =====")
    print(json.dumps(report, indent=2))
    print(f"\nAudit JSON: {output_path}")
    print("READ-ONLY AUDIT COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
