"""Offline, read-only outcome audit for scanner stock-selection snapshots.

This tool labels stored scanner observations with subsequent underlying-stock
returns. It does not import scanner, broker, strategy, or order modules and
does not write reports or alter trading data.

Research basis: Heston, Korajczyk & Sadka (2010) study intraday
cross-sectional continuation and short-horizon reversal; Bailey et al. (2015)
show why repeated strategy selection needs out-of-sample overfit checks; the
QuantLab open-source project documents delayed execution and explicit costs.
These sources motivate measuring forward outcomes and controlling validation
bias; they do not establish that any signal works in this market.

Run one completed session at a time, for example:
    python intraday_selection_replay.py --date 2026-10-27

The output counts are snapshot observations, not independent trades. Repeated
observations of the same symbol/state are correlated and must not be treated as
independent statistical evidence. Option-contract outcomes are intentionally
not inferred for candidates that were never traded.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


HORIZONS_MIN = (5, 15, 30, 60)
MAX_QUOTE_DELAY_SECONDS = 150


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return result if result.tzinfo is not None else None


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def _price_at_or_before(
    series: list[tuple[datetime, float]],
    times: list[datetime],
    target: datetime,
) -> float | None:
    index = bisect_right(times, target) - 1
    if index < 0:
        return None
    when, price = series[index]
    if (target - when).total_seconds() > MAX_QUOTE_DELAY_SECONDS:
        return None
    return price


def _load_snapshots(root: Path, day: str, prices: dict[str, list[tuple[datetime, float]]]) -> list[dict[str, Any]]:
    folder = root / "data" / "signal_snapshots"
    # Prefer the explicit signal snapshots. The analysed file supplements them
    # for candidates not already represented at that exact timestamp.
    sources = (
        (folder / f"{day}.csv", "signal"),
        (folder / f"analysed_{day}.csv", "analysed"),
        (folder / f"radar_{day}.csv", "radar_only"),
    )
    priority = {"radar_only": 1, "analysed": 2, "signal": 3}
    observations: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path, source in sources:
        for row in _read_csv(path):
            when = _timestamp(row.get("time"))
            symbol = str(row.get("symbol") or "").strip().upper()
            direction = str(row.get("direction") or "").strip().upper()
            if when is None or not symbol or direction not in {"BULLISH", "BEARISH"}:
                continue
            price = _float(row.get("ltp"))
            if price is None and source == "radar_only":
                symbol_series = prices.get(symbol, [])
                symbol_times = [point[0] for point in symbol_series]
                price = _price_at_or_before(symbol_series, symbol_times, when)
            if not price or price <= 0:
                continue
            key = (when.isoformat(), symbol, direction)
            # Keep the richest available event when sources overlap.
            if key in observations and priority[observations[key]["source"]] >= priority[source]:
                continue
            passed_raw = row.get("passed")
            passed = (str(passed_raw).strip() == "1") if passed_raw not in (None, "") else False
            observations[key] = {
                "time": when,
                "symbol": symbol,
                "direction": direction,
                "entry_price": price,
                "passed": passed,
                "status": str(row.get("status") or row.get("rejection") or ("OUTSIDE_ANALYSED_SET" if source == "radar_only" else row.get("stage")) or "UNKNOWN"),
                "stage": str(row.get("stage") or ("RADAR_ONLY" if source == "radar_only" else "")),
                "score": _float(row.get("score") or row.get("radar_score")),
                "trade_quality": _float(row.get("trade_quality")),
                "movement_capture": _float(row.get("movement_capture")),
                "relative_volume": _float(row.get("rel_volume") or row.get("relative_volume")),
                "vwap_distance_pct": _float(row.get("vwap_dist_pct") or row.get("vwap_distance_pct")),
                "radar_rank": _float(row.get("rank") or row.get("radar_rank")),
                "source": source,
            }
    if observations:
        return sorted(observations.values(), key=lambda item: (item["time"], item["symbol"], item["direction"]))

    # Older sessions may have cycle reports but predate the throttled snapshot
    # files. Reconstruct a 5-minute state sample from those reports only when
    # no dedicated snapshots exist for the date.
    day_key = day.replace("-", "")
    pattern = re.compile(rf"^intraday_movement_{day_key}_\d+\.json$")
    last_seen: dict[tuple[str, str], tuple[str, datetime]] = {}
    for path in sorted((root / "data" / "reports").glob(f"intraday_movement_{day_key}_*.json")):
        if not pattern.fullmatch(path.name):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        when = _timestamp(payload.get("generated_at"))
        if when is None:
            continue
        for row in payload.get("candidates") or []:
            symbol = str(row.get("symbol") or "").strip().upper()
            direction = str(row.get("direction") or "").strip().upper()
            price = _float(row.get("ltp"))
            if not symbol or direction not in {"BULLISH", "BEARISH"} or not price or price <= 0:
                continue
            stage = str(row.get("stage") or "")
            status = str(row.get("paper_trade_status") or stage or "UNKNOWN")
            passed = bool(row.get("actionable"))
            signature = f"{stage}|{status}|{int(passed)}"
            state_key = (symbol, direction)
            previous = last_seen.get(state_key)
            if previous and previous[0] == signature and (when - previous[1]).total_seconds() < 300:
                continue
            last_seen[state_key] = (signature, when)
            observations[(when.isoformat(), symbol, direction)] = {
                "time": when, "symbol": symbol, "direction": direction,
                "entry_price": price, "passed": passed, "status": status,
                "stage": stage, "score": _float(row.get("score")),
                "trade_quality": _float(row.get("trade_quality_score")),
                "movement_capture": _float(row.get("movement_capture_score")),
                "relative_volume": _float(row.get("relative_volume")),
                "vwap_distance_pct": _float(row.get("vwap_distance_percent")),
                "radar_rank": None, "source": "cycle_report",
            }
    return sorted(observations.values(), key=lambda item: (item["time"], item["symbol"], item["direction"]))


def _load_market_quotes(root: Path, day: str) -> dict[str, list[tuple[datetime, float]]]:
    day_key = day.replace("-", "")
    pattern = re.compile(rf"^intraday_movement_{day_key}_\d+\.json$")
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for path in sorted((root / "data" / "reports").glob(f"intraday_movement_{day_key}_*.json")):
        if not pattern.fullmatch(path.name):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        when = _timestamp(payload.get("generated_at"))
        if when is None:
            continue
        rows = (payload.get("fno_market_watch") or {}).get("rows") or []
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            price = _float(row.get("ltp"))
            if symbol and price is not None and price > 0:
                series[symbol].append((when, price))
    for values in series.values():
        values.sort(key=lambda item: item[0])
    return series


def _load_index(root: Path, day: str) -> list[tuple[datetime, float]]:
    rows = _read_csv(root / "data" / "market_context" / f"{day}.csv")
    out = []
    for row in rows:
        when = _timestamp(row.get("time"))
        price = _float(row.get("nifty_ltp"))
        if when and price and price > 0:
            out.append((when, price))
    return sorted(out, key=lambda item: item[0])


def _price_at_or_after(
    series: list[tuple[datetime, float]],
    times: list[datetime],
    target: datetime,
) -> tuple[datetime, float] | None:
    index = bisect_left(times, target)
    if index >= len(series):
        return None
    when, price = series[index]
    if (when - target).total_seconds() > MAX_QUOTE_DELAY_SECONDS:
        return None
    return when, price


def label_observations(
    observations: list[dict[str, Any]],
    prices: dict[str, list[tuple[datetime, float]]],
    index_prices: list[tuple[datetime, float]],
) -> list[dict[str, Any]]:
    index_times = [item[0] for item in index_prices]
    symbol_times = {symbol: [item[0] for item in rows] for symbol, rows in prices.items()}
    labeled = []
    for observation in observations:
        symbol = observation["symbol"]
        series = prices.get(symbol, [])
        times = symbol_times.get(symbol, [])
        if not series:
            continue
        for horizon in HORIZONS_MIN:
            target = observation["time"] + timedelta(minutes=horizon)
            future = _price_at_or_after(series, times, target)
            if future is None:
                continue
            _, future_price = future
            direction_sign = 1.0 if observation["direction"] == "BULLISH" else -1.0
            row = dict(observation)
            row["horizon_min"] = horizon
            row["directional_stock_return_pct"] = direction_sign * (future_price / observation["entry_price"] - 1.0) * 100.0
            index_start = _price_at_or_after(index_prices, index_times, observation["time"])
            index_future = _price_at_or_after(index_prices, index_times, target)
            if index_start and index_future:
                row["directional_nifty_return_pct"] = direction_sign * (index_future[1] / index_start[1] - 1.0) * 100.0
                row["stock_relative_to_nifty_pct"] = row["directional_stock_return_pct"] - row["directional_nifty_return_pct"]
            else:
                row["directional_nifty_return_pct"] = None
                row["stock_relative_to_nifty_pct"] = None
            labeled.append(row)
    return labeled


def _summarize(rows: list[dict[str, Any]], label: str) -> str:
    if not rows:
        return f"  {label}: no matured observations"
    returns = [row["directional_stock_return_pct"] for row in rows]
    relative = [row["stock_relative_to_nifty_pct"] for row in rows if row["stock_relative_to_nifty_pct"] is not None]
    hits = sum(value > 0 for value in returns)
    med = statistics.median(returns)
    mean = statistics.fmean(returns)
    rel_med = statistics.median(relative) if relative else None
    rel_text = f"; median vs NIFTY {rel_med:+.3f}%" if rel_med is not None else ""
    return f"  {label}: n={len(rows)}; direction-hit={hits / len(rows):.1%}; median={med:+.3f}%; mean={mean:+.3f}%{rel_text}"


def run(root: Path, day: str) -> str:
    prices = _load_market_quotes(root, day)
    observations = _load_snapshots(root, day, prices)
    if not observations:
        return f"No signal/analysed snapshots found for {day}. No files were written."
    index_prices = _load_index(root, day)
    labeled = label_observations(observations, prices, index_prices)
    source_counts = Counter(row["source"] for row in observations)
    lines = [
        f"Offline intraday stock-selection replay - {day}",
        f"Observation rows: {len(observations)}; symbols: {len({x['symbol'] for x in observations})}; sources: {dict(sorted(source_counts.items()))}; labeled horizon rows: {len(labeled)}",
        "Returns are underlying-stock returns after each snapshot, direction-adjusted. These are not option returns or simulated fills.",
        "Repeated observations are correlated; sample counts are not independent trades. No inference of causality or profitability.",
    ]
    for horizon in HORIZONS_MIN:
        subset = [row for row in labeled if row["horizon_min"] == horizon]
        lines.append(f"\n{horizon}-minute forward horizon:")
        groups = (
            ([row for row in subset if row["source"] == "signal" and row["passed"]], "actionable entry-ready"),
            ([row for row in subset if row["source"] == "signal" and not row["passed"]], "entry-ready but held"),
            ([row for row in subset if row["source"] == "analysed"], "pre-entry screened"),
            ([row for row in subset if row["source"] == "radar_only"], "radar-only, outside analysed candidates"),
            ([row for row in subset if row["source"] == "cycle_report" and row["passed"]], "cycle-report actionable"),
            ([row for row in subset if row["source"] == "cycle_report" and not row["passed"]], "cycle-report screened/held"),
        )
        lines.extend(_summarize(group, label) for group, label in groups if group)
        by_direction = defaultdict(list)
        for row in subset:
            by_direction[(row["direction"], row["source"], row["passed"])].append(row)
        for (direction, source, passed), group in sorted(by_direction.items()):
            label = "actionable" if source == "signal" and passed else "held" if source == "signal" else "radar-only" if source == "radar_only" else "cycle-actionable" if source == "cycle_report" and passed else "cycle-screened" if source == "cycle_report" else "screened"
            lines.append(_summarize(group, f"{direction.lower()} {label}"))
    lines.append("\nUse this as a screening diagnostic only. Promote a rule only after session-wise out-of-sample validation, realistic option bid/ask and costs, and enough independent sessions.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Trading date in YYYY-MM-DD format")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent, help="APlus project root")
    args = parser.parse_args()
    try:
        day = date.fromisoformat(args.date).isoformat()
    except ValueError:
        parser.error("--date must be a valid YYYY-MM-DD trading date")
    print(run(args.root.resolve(), day))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
