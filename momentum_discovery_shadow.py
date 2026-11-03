"""Shadow-only one-minute momentum ranking; never imported by live trading.

Ranks bullish and bearish stock candidates independently. Caution conditions
are annotations, not rejection gates. This module has no broker, scanner,
strategy, or order-execution imports.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping


IST_OPEN = 9 * 60 + 15
SIGNAL_CUTOFF = 14 * 60 + 30
SESSION_END = 15 * 60 + 30
SNAPSHOT_INTERVAL_MIN = 5
FORWARD_HORIZON_MIN = 15
FEATURE_COLUMNS = (
    "side", "minute_of_day", "return_5m_pct", "return_10m_pct", "return_15m_pct",
    "relative_volume_15m", "vwap_distance_pct", "session_return_pct",
    "distance_to_20m_level_pct", "breakout_confirmed", "score",
)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _minute(value: Any) -> int | None:
    try:
        hour, minute = str(value).split(":", 1)
        hour, minute = int(hour), int(minute)
        return hour * 60 + minute if 0 <= hour < 24 and 0 <= minute < 60 else None
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def score_at(bars: Mapping[str, list[Any]], index: int) -> dict[str, Any] | None:
    """Score one bar using data available at that bar only.

    A continuous 20-minute history is mandatory. Thresholds and weights are
    fixed v0 research choices, not trained parameters or trading rules.
    """
    minutes = bars.get("minute", [])
    n = len(minutes)
    if index < 20 or index >= n:
        return None
    minute = int(minutes[index])
    if minute > SIGNAL_CUTOFF or minutes[index - 20:index + 1] != list(range(minute - 20, minute + 1)):
        return None
    closes = [_number(v) for v in bars.get("close", [])]
    highs = [_number(v) for v in bars.get("high", [])]
    lows = [_number(v) for v in bars.get("low", [])]
    volumes = [_number(v) for v in bars.get("volume", [])]
    opens = [_number(v) for v in bars.get("open", [])]
    vwap_est = [_number(v) for v in bars.get("vwap_estimate", [])]
    if any(len(values) <= index for values in (closes, highs, lows, volumes, opens, vwap_est)):
        return None
    if any(value is None or value <= 0 for value in closes[index - 20:index + 1]):
        return None
    current = closes[index]
    ret5 = (current / closes[index - 5] - 1.0) * 100.0
    ret10 = (current / closes[index - 10] - 1.0) * 100.0
    ret15 = (current / closes[index - 15] - 1.0) * 100.0
    if ret15 == 0:
        return None
    side = "BULLISH" if ret15 > 0 else "BEARISH"
    direction = 1.0 if side == "BULLISH" else -1.0

    prior_vol = [v for v in volumes[index - 15:index] if v is not None and v > 0]
    current_vol = volumes[index]
    if current_vol is None or current_vol <= 0 or len(prior_vol) < 12:
        return None
    baseline_vol = _median(prior_vol)
    if baseline_vol is None or baseline_vol <= 0:
        return None
    relative_volume = current_vol / baseline_vol
    if len(prior_vol) < 15:
        # The score still emits, but missing volume bars are made explicit.
        volume_baseline_incomplete = True
    else:
        volume_baseline_incomplete = False

    # Session VWAP is an estimate built only from the bar-level volume-weighted
    # LTP estimates available up to this minute. Missing volume bars are omitted.
    weighted = [(price, volume) for price, volume in zip(vwap_est[:index + 1], volumes[:index + 1])
                if price is not None and price > 0 and volume is not None and volume > 0]
    vwap_volume = sum(volume for _, volume in weighted)
    vwap = sum(price * volume for price, volume in weighted) / vwap_volume if vwap_volume else None
    vwap_distance = (current / vwap - 1.0) * 100.0 if vwap else None
    session_open = opens[0]
    if session_open is None or session_open <= 0:
        return None
    session_return = (current / session_open - 1.0) * 100.0

    prior_high = max(highs[index - 20:index]) if all(v is not None for v in highs[index - 20:index]) else None
    prior_low = min(lows[index - 20:index]) if all(v is not None for v in lows[index - 20:index]) else None
    if prior_high is None or prior_low is None:
        return None
    broke_level = current > prior_high if side == "BULLISH" else current < prior_low
    level = prior_high if side == "BULLISH" else prior_low
    level_distance = ((level - current) / current * 100.0 if side == "BULLISH"
                      else (current - level) / current * 100.0)
    vwap_aligned = vwap_distance is not None and vwap_distance * direction > 0
    trend_aligned = ret5 * direction > 0

    # Interpretable, capped, untrained v0 score. Save raw features alongside it.
    score_raw = (
        20.0 * _clamp(abs(ret5) / 0.50)
        + 25.0 * _clamp(abs(ret15) / 1.00)
        + 20.0 * _clamp((relative_volume - 1.0) / 2.0)
        + (15.0 if vwap_aligned else 0.0)
        + (20.0 if broke_level else (10.0 if 0 <= level_distance <= 0.50 else 0.0))
        + (10.0 if trend_aligned else 0.0)
    )
    score = round(min(100.0, score_raw / 1.10), 3)

    cautions: list[str] = []
    if direction * ret5 < 0:
        cautions.append("SHORT_TERM_DIRECTION_CONFLICT")
    if volume_baseline_incomplete:
        cautions.append("VOLUME_BASELINE_INCOMPLETE")
    if direction * ret10 >= 0.85:
        cautions.append("LATE_10M_MOVE_REVIEW")
    vwap_extended = (vwap_distance is not None and direction * vwap_distance > 0.87
                     and (direction * ret5 > 0.25 or direction * ret15 > 0.45))
    if vwap_extended:
        cautions.append("VWAP_EXTENSION_REVIEW")
    if direction * session_return > 2.81 and (direction * ret10 > 0.40 or vwap_extended):
        cautions.append("SESSION_EXTENSION_REVIEW")
    if vwap_distance is not None and not vwap_aligned:
        cautions.append("VWAP_NOT_ALIGNED_REVIEW")
    if broke_level and trend_aligned and vwap_aligned:
        readiness = "BREAKOUT_CONFIRMED_SHADOW"
    elif 0 <= level_distance <= 0.50:
        readiness = "WAITING_NEAR_LEVEL"
    elif "SHORT_TERM_DIRECTION_CONFLICT" in cautions or "VWAP_NOT_ALIGNED_REVIEW" in cautions:
        readiness = "CONFLICT_REVIEW"
    else:
        readiness = "MOMENTUM_RANK_ONLY"
    return {
        "side": side,
        "minute_of_day": minute,
        "return_5m_pct": round(ret5, 6),
        "return_10m_pct": round(ret10, 6),
        "return_15m_pct": round(ret15, 6),
        "relative_volume_15m": round(relative_volume, 6),
        "vwap_distance_pct": round(vwap_distance, 6) if vwap_distance is not None else None,
        "session_return_pct": round(session_return, 6),
        "distance_to_20m_level_pct": round(level_distance, 6),
        "breakout_confirmed": bool(broke_level),
        "score": score,
        "readiness": readiness,
        "cautions": cautions,
        "score_version": "momentum-shadow-v0",
    }


def _bars_by_symbol(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, list[Any]]]:
    raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        minute = _minute(row.get("bar_minute"))
        if not symbol or minute is None or not IST_OPEN <= minute <= SESSION_END:
            continue
        raw[symbol].append({
            "minute": minute,
            "open": _number(row.get("open")),
            "high": _number(row.get("high")),
            "low": _number(row.get("low")),
            "close": _number(row.get("close")),
            "volume": _number(row.get("volume_delta")),
            "vwap_estimate": _number(row.get("volume_weighted_ltp_estimate")),
        })
    result: dict[str, dict[str, list[Any]]] = {}
    for symbol, items in raw.items():
        items.sort(key=lambda item: item["minute"])
        by_minute = {item["minute"]: item for item in items}
        if len(by_minute) != len(items):
            continue
        selected = [by_minute[m] for m in sorted(by_minute)]
        if not selected or selected[0]["minute"] != IST_OPEN:
            continue
        result[symbol] = {key: [item[key] for item in selected]
                          for key in ("minute", "open", "high", "low", "close", "volume", "vwap_estimate")}
    return result


def evaluate_session(rows: Iterable[Mapping[str, Any]], day: str, *, top_n_per_side: int = 5) -> dict[str, Any]:
    """Rank each side at five-minute snapshots and label the next 15 minutes."""
    date.fromisoformat(day)
    by_symbol = _bars_by_symbol(rows)
    indexed: dict[str, dict[int, int]] = {
        symbol: {minute: i for i, minute in enumerate(bars["minute"])}
        for symbol, bars in by_symbol.items()
    }
    selections: list[dict[str, Any]] = []
    for snapshot in range(IST_OPEN + 20, SIGNAL_CUTOFF + 1, SNAPSHOT_INTERVAL_MIN):
        for side in ("BULLISH", "BEARISH"):
            ranked = []
            for symbol, bars in by_symbol.items():
                i = indexed[symbol].get(snapshot)
                if i is None:
                    continue
                scored = score_at(bars, i)
                if scored is not None and scored["side"] == side:
                    ranked.append({"symbol": symbol, **scored})
            ranked.sort(key=lambda item: (-item["score"], item["symbol"]))
            for rank, item in enumerate(ranked[:top_n_per_side], start=1):
                bars = by_symbol[item["symbol"]]
                i = indexed[item["symbol"]][snapshot]
                future_minutes = bars["minute"][i + 1:i + 1 + FORWARD_HORIZON_MIN]
                future_ok = future_minutes == list(range(snapshot + 1, snapshot + 1 + FORWARD_HORIZON_MIN))
                future_highs = [_number(v) for v in bars["high"][i + 1:i + 1 + FORWARD_HORIZON_MIN]]
                future_lows = [_number(v) for v in bars["low"][i + 1:i + 1 + FORWARD_HORIZON_MIN]]
                future_closes = [_number(v) for v in bars["close"][i + 1:i + 1 + FORWARD_HORIZON_MIN]]
                price = _number(bars["close"][i])
                if future_ok and price and all(v is not None for v in future_highs + future_lows + future_closes):
                    if side == "BULLISH":
                        best = (max(future_highs) / price - 1) * 100
                        worst = (min(future_lows) / price - 1) * 100
                        close_return = (future_closes[-1] / price - 1) * 100
                    else:
                        best = (1 - min(future_lows) / price) * 100
                        worst = (1 - max(future_highs) / price) * 100
                        close_return = (1 - future_closes[-1] / price) * 100
                else:
                    best = worst = close_return = None
                selections.append({
                    "day": day,
                    "snapshot_minute": snapshot,
                    "symbol": item["symbol"],
                    "side": side,
                    "rank": rank,
                    **{key: item[key] for key in FEATURE_COLUMNS},
                    "readiness": item["readiness"],
                    "cautions": item["cautions"],
                    "forward_15m_best_pct": round(best, 6) if best is not None else None,
                    "forward_15m_worst_pct": round(worst, 6) if worst is not None else None,
                    "forward_15m_close_pct": round(close_return, 6) if close_return is not None else None,
                })
    complete = [row for row in selections if row["forward_15m_close_pct"] is not None]
    close_returns = [row["forward_15m_close_pct"] for row in complete]
    best_returns = [row["forward_15m_best_pct"] for row in complete]
    worst_returns = [row["forward_15m_worst_pct"] for row in complete]
    return {
        "day": day,
        "research_only": True,
        "not_option_pnl_or_live_strategy_performance": True,
        "score_version": "momentum-shadow-v0",
        "feature_columns": list(FEATURE_COLUMNS),
        "method": {
            "snapshot_interval_minutes": SNAPSHOT_INTERVAL_MIN,
            "first_snapshot": "09:35 IST",
            "last_signal_snapshot": "14:30 IST",
            "top_n_per_side_per_snapshot": top_n_per_side,
            "forward_horizon_minutes": FORWARD_HORIZON_MIN,
            "decision_time_only_features": True,
            "caution_rules_remove_candidates": False,
            "weights_trained": False,
            "vwap_source": "cumulative bar volume-weighted LTP estimate; may be incomplete",
        },
        "counts": {
            "symbols_with_opening_bar": len(by_symbol),
            "ranked_rows": len(selections),
            "complete_forward_outcomes": len(complete),
            "incomplete_forward_outcomes": len(selections) - len(complete),
            "positive_15m_close_count": sum(value > 0 for value in close_returns),
            "negative_15m_close_count": sum(value < 0 for value in close_returns),
        },
        "summary": {
            "positive_15m_close_pct": round(100 * sum(value > 0 for value in close_returns) / len(complete), 3) if complete else None,
            "median_15m_close_return_pct": round(statistics.median(close_returns), 6) if complete else None,
            "median_15m_best_excursion_pct": round(statistics.median(best_returns), 6) if complete else None,
            "median_15m_worst_excursion_pct": round(statistics.median(worst_returns), 6) if complete else None,
            "readiness_counts": dict(Counter(row["readiness"] for row in selections)),
            "caution_counts": dict(Counter(tag for row in selections for tag in row["cautions"])),
        },
        "limitations": [
            "Two clean broad sessions are insufficient to estimate generalization or profitability.",
            "Snapshots overlap in time and repeated symbols are not independent observations.",
            "Underlying price excursions are not option returns and omit costs, fills, and exits.",
            "The heuristic score is untrained and its thresholds require untouched-session validation.",
            "No sector, index, news, order-flow, or reliable option-liquidity features are present.",
        ],
        "selections": selections,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day", help="Session date YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--top", type=int, default=5, help="Top candidates per side per snapshot")
    parser.add_argument("--write", action="store_true", help="Write a new report; refuse to overwrite")
    parser.add_argument("--output", type=Path, help="Report path used with --write")
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be at least 1")
    date.fromisoformat(args.day)
    source = args.root / "data" / "shadow_1m" / args.day / "stocks_1m.csv"
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        report = evaluate_session(csv.DictReader(handle), args.day, top_n_per_side=args.top)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        target = args.output or (args.root / "data" / "shadow_1m" / args.day / "momentum_discovery_shadow.json")
        with target.open("x", encoding="utf-8", newline="") as handle:
            handle.write(encoded)
        print(target)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
