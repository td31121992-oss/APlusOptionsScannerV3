"""Read-only 1m OHLCV download and isolated 3m breakout shadow replay.

No orders, no production imports, no paper-trade ledger writes.
Outputs are written only beneath data/three_minute_shadow_replay/.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
OUT = ROOT / "data" / "three_minute_shadow_replay"
REPORT = ROOT / "data" / "reports" / "fno_market_watch_latest.json"

from breakout_breakdown_shadow import (
    BreakoutConfig,
    MinuteBar,
    aggregate_three_minute_bars,
    classify_breakout_breakdown,
    evaluate_forward_outcome,
    same_slot_relative_volume,
)


def load_universe(path: Path, limit: int = 0) -> list[tuple[str, str]]:
    if not path.is_file():
        raise SystemExit(f"Missing universe report: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    rows = obj.get("rows", []) if isinstance(obj, dict) else []
    universe, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        sid = str(row.get("security_id") or "").strip()
        if symbol and sid and sid not in seen:
            seen.add(sid)
            universe.append((symbol, sid))
    universe.sort()
    if limit > 0:
        universe = universe[:limit]
    if not universe:
        raise SystemExit("No symbol/security_id pairs found in market-watch report.")
    return universe


def write_rows(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=28, help="calendar-day history; API supports up to one month for 1m candles")
    parser.add_argument("--limit", type=int, default=0, help="limit symbols for a smoke test; 0 means all symbols")
    parser.add_argument("--sleep", type=float, default=0.15, help="extra delay between symbols")
    parser.add_argument("--min-history-sessions", type=int, default=5)
    args = parser.parse_args()
    if not 7 <= args.days <= 30:
        parser.error("--days must be between 7 and 30")
    if args.min_history_sessions < 5:
        parser.error("--min-history-sessions must be at least 5 to avoid weak volume baselines")

    universe = load_universe(REPORT, args.limit)
    now = datetime.now(IST)
    start_day = (now - timedelta(days=args.days)).date()
    end_day = now.date()
    print("=" * 88)
    print("APLUS 3-MINUTE BREAKOUT/BREAKDOWN SHADOW REPLAY — READ ONLY")
    print(f"Universe: {len(universe)} | Range: {start_day} to {end_day} | Interval source: 1-minute OHLCV")
    print("No trade authorization, order calls, production scanner edits, or paper-ledger writes.")
    print("=" * 88)

    # Cache raw candles by symbol. Failures remain explicit in the coverage report.
    from core.upstox_client import UpstoxClient
    client = UpstoxClient()
    raw_rows: list[dict] = []
    bars_by_symbol_day: dict[str, dict[str, list]] = defaultdict(dict)
    failures: list[dict] = []
    symbol_coverage: list[dict] = []

    for idx, (symbol, sid) in enumerate(universe, 1):
        try:
            response = client.get_intraday_candles(
                security_id=sid, segment="NSE_EQ", instrument="EQUITY", interval=1,
                from_datetime=datetime.combine(start_day, dtime(9, 0), tzinfo=IST),
                to_datetime=datetime.combine(end_day, dtime(15, 35), tzinfo=IST),
                oi=False,
            )
            arrays = [response.get(k, []) for k in ("timestamp", "open", "high", "low", "close", "volume")]
            n = min((len(a) for a in arrays), default=0)
            symbol_rows = []
            minute_bars = []
            for i in range(n):
                ts = datetime.fromtimestamp(float(arrays[0][i]), IST)
                bar = MinuteBar(ts, float(arrays[1][i]), float(arrays[2][i]),
                                float(arrays[3][i]), float(arrays[4][i]), int(float(arrays[5][i])))
                minute_bars.append(bar)
                row = {"symbol": symbol, "security_id": sid, "timestamp": ts.isoformat(),
                       "date": ts.date().isoformat(), "minute": ts.strftime("%H:%M"),
                       "open": bar.open, "high": bar.high, "low": bar.low,
                       "close": bar.close, "volume": bar.volume}
                symbol_rows.append(row)
                raw_rows.append(row)
            grouped = defaultdict(list)
            for bar in minute_bars:
                grouped[bar.timestamp.date().isoformat()].append(bar)
            for day, bars in grouped.items():
                bars_by_symbol_day[symbol][day] = aggregate_three_minute_bars(bars)
            valid_days = sum(bool(v) for v in bars_by_symbol_day[symbol].values())
            symbol_coverage.append({"symbol": symbol, "security_id": sid, "minute_rows": n,
                                    "session_days_with_3m_bars": valid_days,
                                    "three_minute_bars": sum(len(v) for v in bars_by_symbol_day[symbol].values()),
                                    "status": "OK" if n else "EMPTY"})
            print(f"[{idx:03d}/{len(universe):03d}] {symbol:<16} 1m={n:>5} sessions={valid_days:>2}")
        except Exception as exc:
            failures.append({"symbol": symbol, "security_id": sid,
                             "error": f"{type(exc).__name__}: {exc}"})
            symbol_coverage.append({"symbol": symbol, "security_id": sid, "minute_rows": 0,
                                    "session_days_with_3m_bars": 0, "three_minute_bars": 0,
                                    "status": "FAILED"})
            print(f"[{idx:03d}/{len(universe):03d}] {symbol:<16} FAILED: {type(exc).__name__}: {exc}")
        time.sleep(max(0.0, args.sleep))

    OUT.mkdir(parents=True, exist_ok=True)
    raw_fields = ["symbol", "security_id", "timestamp", "date", "minute", "open", "high", "low", "close", "volume"]
    write_rows(OUT / "underlying_1m_ohlcv.csv", raw_rows, raw_fields)

    three_rows = []
    for symbol, day_map in bars_by_symbol_day.items():
        sid = next((x[1] for x in universe if x[0] == symbol), "")
        for day, bars in sorted(day_map.items()):
            for b in bars:
                three_rows.append({"symbol": symbol, "security_id": sid, "date": day,
                                   "timestamp": b.timestamp.isoformat(), "open": b.open, "high": b.high,
                                   "low": b.low, "close": b.close, "volume": b.volume})
    write_rows(OUT / "underlying_3m_ohlcv.csv", three_rows,
               ["symbol", "security_id", "date", "timestamp", "open", "high", "low", "close", "volume"])

    # Replay in chronological order. Relative volume uses only prior sessions at the same 3m slot.
    config = BreakoutConfig(minimum_history_sessions=args.min_history_sessions)
    candidates: list[dict] = []
    per_symbol_days = {
        symbol: sorted(day_map) for symbol, day_map in bars_by_symbol_day.items()
    }
    for symbol, day_map in bars_by_symbol_day.items():
        days = per_symbol_days[symbol]
        for day_idx, day in enumerate(days):
            bars = day_map[day]
            if not bars:
                continue
            prior_days = days[:day_idx]
            cumulative_pv = 0.0
            cumulative_volume = 0
            for i, bar in enumerate(bars):
                cumulative_pv += ((bar.high + bar.low + bar.close) / 3.0) * bar.volume
                cumulative_volume += bar.volume
                vwap = cumulative_pv / cumulative_volume if cumulative_volume > 0 else None
                # Match the actual wall-clock slot, not list index: missing buckets
                # are omitted by the aggregator and must not shift historical baselines.
                slot = bar.timestamp.strftime("%H:%M")
                prior_slot_volumes = []
                for prior_day in prior_days:
                    prior_bars = day_map[prior_day]
                    match = next((pb for pb in prior_bars
                                  if pb.timestamp.strftime("%H:%M") == slot), None)
                    if match is not None:
                        prior_slot_volumes.append(match.volume)
                relvol = same_slot_relative_volume(
                    bar.volume, prior_slot_volumes, minimum_sessions=args.min_history_sessions
                )
                signal = classify_breakout_breakdown(
                    symbol=symbol, bars=bars[:i + 1], relative_volume=relvol, vwap=vwap, config=config
                )
                if signal.direction not in {"BULLISH", "BEARISH"}:
                    continue
                future = bars[i + 1:i + 6]
                outcome = evaluate_forward_outcome(
                    signal=signal, entry_price=bar.close, future_bars=future, horizon_bars=5
                )
                candidates.append({
                    "symbol": symbol, "date": day, "timestamp": signal.timestamp,
                    "direction": signal.direction, "verdict": signal.verdict, "score": signal.score,
                    "trigger_level": signal.trigger_level, "close": signal.close,
                    "relative_volume": signal.relative_volume, "vwap": signal.vwap,
                    "mfe_percent": outcome.get("mfe_percent"), "mae_percent": outcome.get("mae_percent"),
                    "close_return_percent": outcome.get("close_return_percent"),
                    "bars_observed": outcome.get("bars_observed"),
                    "horizon_complete": outcome.get("horizon_complete"),
                    "reasons": " | ".join(signal.reasons),
                    "shadow_only": True, "trade_authorized": False,
                })

    candidate_fields = ["symbol", "date", "timestamp", "direction", "verdict", "score", "trigger_level",
                        "close", "relative_volume", "vwap", "mfe_percent", "mae_percent",
                        "close_return_percent", "bars_observed", "horizon_complete", "reasons",
                        "shadow_only", "trade_authorized"]
    write_rows(OUT / "shadow_candidates_outcomes.csv", candidates, candidate_fields)
    # A separate JSONL file contains candidate events only, never the production journal.
    with (OUT / "shadow_candidates.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in candidates:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    confirmed = [r for r in candidates if r["verdict"] == "SHADOW_CONFIRMED"]
    complete = [r for r in candidates if r.get("horizon_complete") is True]
    summary = {
        "run_at_ist": datetime.now(IST).isoformat(),
        "provider": "Upstox historical candles via existing read-only client",
        "requested_calendar_days": args.days,
        "start_date": start_day.isoformat(), "end_date": end_day.isoformat(),
        "universe_symbols": len(universe), "symbols_with_data": sum(r["minute_rows"] > 0 for r in symbol_coverage),
        "failed_symbols": len(failures), "minute_ohlcv_rows": len(raw_rows),
        "three_minute_ohlcv_rows": len(three_rows), "candidate_signals": len(candidates),
        "shadow_confirmed": len(confirmed), "complete_5_bar_outcomes": len(complete),
        "outcome_coverage_pct": round(100 * len(complete) / len(candidates), 2) if candidates else None,
        "confirmed_complete_outcomes": sum(r in complete for r in confirmed),
        "important_limitations": [
            "This is underlying-stock OHLCV replay, not option-premium/P&L replay.",
            "Relative volume is unavailable until at least five prior sessions have a valid same-slot bar.",
            "Symbols with failed/empty data are listed; results are not universe-complete unless all expected symbols have adequate coverage.",
            "No strategy profitability claim is made; compare coverage and outcomes before considering any production integration.",
        ],
        "coverage": symbol_coverage,
        "failures": failures,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("=" * 88)
    print("REPLAY COMPLETE")
    print(f"1m rows: {len(raw_rows)} | 3m bars: {len(three_rows)} | directional candidates: {len(candidates)}")
    print(f"Shadow confirmed: {len(confirmed)} | complete 5-bar outcomes: {len(complete)}")
    print(f"Symbols with data: {summary['symbols_with_data']}/{len(universe)} | failed: {len(failures)}")
    print(f"Output folder: {OUT}")
    print("Review summary.json coverage before interpreting any outcome statistics.")
    print("=" * 88)
    return 0 if raw_rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
