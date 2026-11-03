"""Offline, research-only evaluation of recorded 1-minute pre-breakout labels.

Reads the shadow candle CSV created after the session. It has no broker,
scanner, dashboard, or trading imports and does not produce option P&L.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

import prebreakout_shadow


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _minute(value: Any) -> int | None:
    try:
        hour, minute = str(value).split(":", 1)
        h, m = int(hour), int(minute)
        return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def evaluate_rows(rows: Iterable[Mapping[str, Any]], day: str) -> dict[str, Any]:
    """Evaluate one session using only complete observed 1-minute rows.

    The first three consecutive bars from 09:15 IST define opening range.
    Candidates require three preceding positive recorded-volume bars. For
    comparable labels, a candidate is included only when its next 18 observed
    bars are consecutive (six confirmation minutes plus twelve outcome
    minutes); otherwise it is counted as outcome-ineligible.
    """
    date.fromisoformat(day)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        symbol = str(source.get("symbol") or "").strip().upper()
        minute = _minute(source.get("bar_minute"))
        # Keep post-cutoff bars for forward outcomes. Candidate generation
        # itself enforces the 14:30 signal cutoff.
        if not symbol or minute is None or not (9 * 60 + 15 <= minute <= 15 * 60 + 30):
            continue
        values = {key: _as_float(source.get(key)) for key in ("open", "high", "low", "close", "volume_delta")}
        if any(value is None for value in values.values()):
            continue
        grouped[symbol].append({"minute": minute, **values})

    symbols: dict[str, dict[str, Any]] = {}
    symbols_with_open = 0
    excluded_opening = 0
    for symbol, source_bars in grouped.items():
        ordered = sorted(source_bars, key=lambda bar: bar["minute"])
        # Keep a single deterministic row per minute; ambiguous duplicates
        # invalidate that minute rather than selecting an arbitrary quote.
        counts: dict[int, int] = defaultdict(int)
        for bar in ordered:
            counts[bar["minute"]] += 1
        bars = [bar for bar in ordered if counts[bar["minute"]] == 1]
        if len(bars) < 4 or [bar["minute"] for bar in bars[:3]] != [555, 556, 557]:
            excluded_opening += 1
            continue
        symbols_with_open += 1
        symbols[symbol] = {
            "minute": [bar["minute"] for bar in bars],
            "open": [bar["open"] for bar in bars],
            "high": [bar["high"] for bar in bars],
            "low": [bar["low"] for bar in bars],
            "close": [bar["close"] for bar in bars],
            "volume": [bar["volume_delta"] for bar in bars],
        }

    candidates = prebreakout_shadow.candidates_for_day(
        symbols,
        max_level_distance_pct=0.60,
        min_volume_multiple=1.30,
        require_complete_volume_window=True,
    )
    outcomes: list[dict[str, Any]] = []
    outcome_ineligible = 0
    for candidate in candidates:
        bars = symbols[candidate["symbol"]]
        minutes = bars["minute"]
        signal_i = minutes.index(candidate["minute"])
        # Need a full confirmation window and a full 12-bar outcome window
        # after the latest possible confirmation. Missing candles are not
        # forward-filled.
        future = minutes[signal_i + 1:signal_i + 19]
        if len(future) != 18 or future != list(range(candidate["minute"] + 1, candidate["minute"] + 19)):
            outcome_ineligible += 1
            continue
        label = prebreakout_shadow.evaluate_candidate(candidate, bars, confirm_bars=6, outcome_bars=12)
        outcomes.append({**candidate, **label})

    confirmed = [row for row in outcomes if row["confirmed"]]
    full = [row for row in confirmed if row["forward_best_pct"] is not None and row["forward_worst_pct"] is not None]
    best = [row["forward_best_pct"] for row in full]
    worst = [row["forward_worst_pct"] for row in full]
    return {
        "day": day,
        "timezone": "Asia/Kolkata",
        "research_only": True,
        "data_type": "underlying_stock_price_excursions_only",
        "not_option_pnl_or_live_strategy_performance": True,
        "method": {
            "timeframe": "1 minute",
            "opening_range": "first three consecutive bars beginning 09:15 IST",
            "candidate_cutoff": "14:30 IST",
            "max_level_distance_pct": 0.60,
            "min_volume_multiple": 1.30,
            "complete_positive_prior_volume_bars_required": 3,
            "levels": "opening-range high/low only; prior-day levels unavailable",
            "confirmation_window_bars": 6,
            "outcome_window_bars": 12,
            "incomplete_or_gapped_outcome_windows": "excluded, never filled",
        },
        "counts": {
            "symbols_with_valid_opening_range": symbols_with_open,
            "symbols_excluded_for_missing_or_ambiguous_opening_bars": excluded_opening,
            "candidates": len(candidates),
            "outcome_ineligible_candidates": outcome_ineligible,
            "eligible_candidates": len(outcomes),
            "confirmed": len(confirmed),
            "not_confirmed_within_window": len(outcomes) - len(confirmed),
            "confirmed_with_full_12_bar_outcome": len(full),
        },
        "summary": {
            "confirmation_rate_pct": round(len(confirmed) / len(outcomes) * 100, 3) if outcomes else None,
            "median_directional_best_pct": _median(best),
            "median_directional_worst_pct": _median(worst),
            "count_best_at_least_1pct": sum(value >= 1.0 for value in best),
            "count_worst_at_or_below_minus_1pct": sum(value <= -1.0 for value in worst),
            "bullish_confirmed": sum(row["side"] == "BULLISH" for row in confirmed),
            "bearish_confirmed": sum(row["side"] == "BEARISH" for row in confirmed),
        },
        "candidate_labels": outcomes,
        "limitations": [
            "One session is insufficient to infer a durable edge.",
            "Recorded volume deltas may undercount after recorder restarts.",
            "No VWAP, news, index context, transaction costs, option marks, fill model, or exit rules are evaluated.",
            "The output is a research label, not a trade recommendation or production signal.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day", help="Session date YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--write", action="store_true", help="Write a new report; refuse to overwrite an existing one")
    parser.add_argument("--output", type=Path, help="Optional report path used with --write")
    args = parser.parse_args()
    source = args.root / "data" / "shadow_1m" / args.day / "stocks_1m.csv"
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        report = evaluate_rows(csv.DictReader(handle), args.day)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        target = args.output or (args.root / "data" / "shadow_1m" / args.day / "prebreakout_evaluation.json")
        with target.open("x", encoding="utf-8", newline="") as handle:
            handle.write(encoded)
        print(target)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
