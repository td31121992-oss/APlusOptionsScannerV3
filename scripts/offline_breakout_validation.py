"""Offline out-of-sample validation for OHLCV breakout research; never places orders."""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

# When executed as "python scripts/offline_breakout_validation.py", Python puts
# the scripts directory (not the repository root) first on sys.path.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.offline_breakout_replay import (
    DEFAULT_DATA, DEFAULT_OUT, HORIZONS, evaluate_signal, find_signals, load_candles, session_key,
)

DEFAULT_VALIDATION_OUT = DEFAULT_OUT / "validation"
NON_OVERLAP_BARS = 5
PULLBACK_WINDOW_BARS = 5
PULLBACK_TOLERANCE = 0.002


def trend_aligned(bars, index, side):
    """Use only bars at or before the signal close; require price and SMA slope alignment."""
    if index < 40:
        return False
    current_close = bars[index]["close"]
    prior20 = mean(bar["close"] for bar in bars[index - 20:index])
    prior20_before = mean(bar["close"] for bar in bars[index - 40:index - 20])
    if side == "LONG_BREAKOUT":
        return current_close > prior20 and prior20 > prior20_before
    return current_close < prior20 and prior20 < prior20_before


def find_pullback_entry(signal, max_bars=PULLBACK_WINDOW_BARS):
    """Find first later bar that retests the broken level and closes back beyond it."""
    bars, index, side = signal["_bars"], signal["_index"], signal["side"]
    level = signal["prior_20_high"] if side == "LONG_BREAKOUT" else signal["prior_20_low"]
    stop = min(len(bars), index + max_bars + 1)
    for entry_index in range(index + 1, stop):
        bar = bars[entry_index]
        if side == "LONG_BREAKOUT":
            touched = bar["low"] <= level * (1 + PULLBACK_TOLERANCE)
            confirmed = bar["close"] > level and bar["close"] >= bar["open"]
        else:
            touched = bar["high"] >= level * (1 - PULLBACK_TOLERANCE)
            confirmed = bar["close"] < level and bar["close"] <= bar["open"]
        if touched and confirmed:
            return entry_index, bar["close"], bar["timestamp"].isoformat()
    return None


def evaluate_from_entry(bars, entry_index, entry_price, side, horizon):
    future = bars[entry_index + 1:entry_index + 1 + horizon]
    if len(future) != horizon:
        return None
    if side == "LONG_BREAKOUT":
        ret = (future[-1]["close"] / entry_price - 1) * 100
        mfe = (max(bar["high"] for bar in future) / entry_price - 1) * 100
        mae = (min(bar["low"] for bar in future) / entry_price - 1) * 100
    else:
        ret = (entry_price / future[-1]["close"] - 1) * 100
        mfe = (entry_price / min(bar["low"] for bar in future) - 1) * 100
        mae = (entry_price / max(bar["high"] for bar in future) - 1) * 100
    return {
        "exit_timestamp": future[-1]["timestamp"].isoformat(),
        "directional_return_pct": ret, "mfe_pct": mfe, "mae_pct": mae,
        "positive_at_horizon": ret > 0,
    }


def chronological_split(dates, train_fraction=0.70):
    ordered = sorted(set(dates))
    if len(ordered) < 2:
        return set(ordered), set()
    cut = max(1, min(len(ordered) - 1, int(len(ordered) * train_fraction)))
    return set(ordered[:cut]), set(ordered[cut:])


def make_candidates(candles, symbol, interval):
    signals = find_signals(candles, symbol, interval)
    by_day = defaultdict(list)
    for signal in signals:
        by_day[signal["session_date"]].append(signal)
    candidates = []
    for day, day_signals in by_day.items():
        dates = sorted({session_key(bar) for bar in day_signals[0]["_bars"]})
        # Split is assigned later per input file; this placeholder is unused.
        for signal in day_signals:
            bars, index = signal["_bars"], signal["_index"]
            pullback = find_pullback_entry(signal)
            candidates.append({
                "symbol": symbol, "interval_minutes": interval, "session_date": day,
                "signal_timestamp": signal["timestamp"], "side": signal["side"],
                "signal_index": index, "entry_index": index,
                "entry_timestamp": signal["timestamp"],
                "entry_price": signal["entry_reference_close"],
                "volume_confirmed": bool(signal["volume_confirmed"]),
                "volume_ratio": signal["volume_ratio"],
                "trend_aligned": trend_aligned(bars, index, signal["side"]),
                "pullback_available": pullback is not None,
                "pullback_entry_index": pullback[0] if pullback else "",
                "pullback_entry_price": pullback[1] if pullback else "",
                "pullback_entry_timestamp": pullback[2] if pullback else "",
                "_bars": bars,
            })
    return candidates


def build_rows(candidates, train_dates):
    variants = ("baseline", "volume_confirmed", "trend_aligned", "volume_and_trend", "pullback_entry")
    rows = []
    for candidate in candidates:
        for variant in variants:
            if variant == "volume_confirmed" and not candidate["volume_confirmed"]:
                continue
            if variant == "trend_aligned" and not candidate["trend_aligned"]:
                continue
            if variant == "volume_and_trend" and not (candidate["volume_confirmed"] and candidate["trend_aligned"]):
                continue
            if variant == "pullback_entry" and not candidate["pullback_available"]:
                continue
            is_pullback = variant == "pullback_entry"
            entry_index = candidate["pullback_entry_index"] if is_pullback else candidate["entry_index"]
            entry_price = candidate["pullback_entry_price"] if is_pullback else candidate["entry_price"]
            entry_timestamp = candidate["pullback_entry_timestamp"] if is_pullback else candidate["entry_timestamp"]
            for horizon in HORIZONS:
                outcome = evaluate_from_entry(
                    candidate["_bars"], int(entry_index), float(entry_price), candidate["side"], horizon
                )
                row = {
                    key: value for key, value in candidate.items()
                    if not key.startswith("_") and key not in ("entry_index", "entry_price", "entry_timestamp")
                }
                row.update({
                    "filter_variant": variant,
                    "entry_timestamp": entry_timestamp,
                    "entry_price": entry_price,
                    "horizon_bars": horizon,
                    "horizon_minutes": horizon * candidate["interval_minutes"],
                    "outcome_available": outcome is not None,
                    "split": "train" if candidate["session_date"] in train_dates else "test",
                })
                if outcome:
                    row.update(outcome)
                else:
                    row.update({"exit_timestamp": "", "directional_return_pct": "", "mfe_pct": "",
                                "mae_pct": "", "positive_at_horizon": ""})
                rows.append(row)
    return rows


def apply_overlap_control(rows, min_gap_bars=NON_OVERLAP_BARS):
    """Mark all horizon rows consistently while spacing signals within symbol/session/side/filter."""
    chosen = defaultdict(list)
    decisions = {}
    ordered = sorted(rows, key=lambda r: (r["symbol"], r["session_date"], r["side"],
                                          r["filter_variant"], r["signal_timestamp"], r["horizon_bars"]))
    for row in ordered:
        key = (row["symbol"], row["session_date"], row["side"], row["filter_variant"])
        signal_key = key + (row["signal_timestamp"],)
        if signal_key not in decisions:
            index = int(row["signal_index"])
            accepted = not chosen[key] or index - chosen[key][-1] >= min_gap_bars
            decisions[signal_key] = accepted
            if accepted:
                chosen[key].append(index)
        row["non_overlapping"] = decisions[signal_key]
    return rows

def summarize(rows):
    if not rows:
        return {"n": 0}
    returns = [float(row["directional_return_pct"]) for row in rows]
    return {
        "n": len(rows),
        "positive_at_horizon_pct": round(100 * sum(value > 0 for value in returns) / len(returns), 2),
        "mean_directional_return_pct": round(mean(returns), 5),
        "median_directional_return_pct": round(median(returns), 5),
        "mean_mfe_pct": round(mean(float(row["mfe_pct"]) for row in rows), 5),
        "mean_mae_pct": round(mean(float(row["mae_pct"]) for row in rows), 5),
    }


def run(data_dir=DEFAULT_DATA, out_dir=DEFAULT_VALIDATION_OUT, intervals=(3, 5), symbols=None):
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    files = []
    for interval in intervals:
        files.extend(sorted(data_dir.glob(f"*_{interval}m.csv")))
    if symbols:
        allow = {value.strip().upper() for value in symbols}
        files = [path for path in files if path.stem.rsplit("_", 1)[0].upper() in allow]
    if not files:
        raise RuntimeError(f"No matching candle CSVs found under {data_dir}")

    all_rows, file_quality = [], []
    for path in files:
        symbol, interval_text = path.stem.rsplit("_", 1)
        interval = int(interval_text[:-1])
        try:
            candles = load_candles(path)
            sessions = sorted({session_key(bar) for bar in candles})
            train_dates, test_dates = chronological_split(sessions)
            candidates = make_candidates(candles, symbol, interval)
            rows = build_rows(candidates, train_dates)
            all_rows.extend(rows)
            file_quality.append({
                "file": path.name, "symbol": symbol, "interval_minutes": interval, "status": "ok",
                "candles": len(candles), "sessions": len(sessions), "train_sessions": len(train_dates),
                "test_sessions": len(test_dates), "signals": len(candidates),
                "pullback_candidates": sum(item["pullback_available"] for item in candidates),
            })
        except Exception as exc:
            file_quality.append({"file": path.name, "symbol": symbol, "interval_minutes": interval,
                                 "status": "error", "error": str(exc)})
    apply_overlap_control(all_rows)

    # Keep only complete outcomes in aggregate statistics. Raw and spaced variants are both reported.
    summaries = []
    for split in ("train", "test"):
        for interval in intervals:
            for horizon in HORIZONS:
                for side in ("LONG_BREAKOUT", "SHORT_BREAKDOWN"):
                    for variant in ("baseline", "volume_confirmed", "trend_aligned", "volume_and_trend", "pullback_entry"):
                        for overlap in ("all_signals", "non_overlapping"):
                            group = [row for row in all_rows if row["split"] == split
                                     and row["interval_minutes"] == interval
                                     and row["horizon_bars"] == horizon and row["side"] == side
                                     and row["filter_variant"] == variant and row["outcome_available"]
                                     and (overlap == "all_signals" or row["non_overlapping"])]
                            item = {"split": split, "interval_minutes": interval,
                                    "horizon_bars": horizon, "horizon_minutes": horizon * interval,
                                    "side": side, "filter_variant": variant, "signal_sample": overlap}
                            item.update(summarize(group))
                            summaries.append(item)

    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "breakout_validation_events.csv"
    columns = [
        "symbol", "interval_minutes", "session_date", "split", "signal_timestamp", "side",
        "filter_variant", "volume_confirmed", "volume_ratio", "trend_aligned", "pullback_available",
        "entry_timestamp", "entry_price", "horizon_bars", "horizon_minutes", "exit_timestamp",
        "directional_return_pct", "mfe_pct", "mae_pct", "positive_at_horizon", "outcome_available",
        "non_overlapping", "signal_index", "pullback_entry_timestamp",
    ]
    with events_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    summary_path = out_dir / "breakout_validation_summary.json"
    report = {
        "mode": "offline_read_only_out_of_sample_research",
        "source": "local Upstox historical OHLCV CSVs",
        "split": "Chronological 70% of each file's sessions for train, final 30% for test; no random shuffle.",
        "filters": {
            "baseline": "20-bar prior-range close crossing",
            "volume_confirmed": "Signal candle volume >= 1.5x previous 20-bar average",
            "trend_aligned": "Signal close and 20-bar mean align with the prior 20-bar mean slope; needs 40 prior bars",
            "volume_and_trend": "Both volume confirmation and trend alignment",
            "pullback_entry": f"Within {PULLBACK_WINDOW_BARS} later bars, retest the broken range level within {PULLBACK_TOLERANCE:.1%} and close back beyond it in directional candle",
            "non_overlapping": f"Signals spaced at least {NON_OVERLAP_BARS} bars apart per symbol/session/side/filter; based on signal bars",
        },
        "input_files": len(files),
        "files_ok": sum(item["status"] == "ok" for item in file_quality),
        "files_with_errors": [item for item in file_quality if item["status"] != "ok"],
        "candles": sum(item.get("candles", 0) for item in file_quality),
        "signals": sum(item.get("signals", 0) for item in file_quality),
        "event_rows": len(all_rows),
        "complete_outcomes": sum(bool(row["outcome_available"]) for row in all_rows),
        "summary": summaries,
        "file_quality": file_quality,
        "limitations": [
            "Underlying directional price returns only, not option premium P&L.",
            "No brokerage, spread, slippage, fill model, or position sizing.",
            "OHLCV is not true bid/ask-at-price footprint data.",
            "A 19-session sample is exploratory; out-of-sample results may still be noisy.",
            "Multiple symbols share market regimes; signal rows are not independent observations.",
            "Date grouping follows timestamp's own date; validate timezone and exchange-session completeness.",
            "The pullback rule is a research definition, not the live scanner's entry logic.",
            "No scanner, broker, order, or trading/risk configuration is imported or modified.",
        ],
    }
    summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Input files: {len(files)}; valid: {report['files_ok']}; errors: {len(report['files_with_errors'])}")
    print(f"Candles: {report['candles']}; signals: {report['signals']}; event rows: {report['event_rows']}")
    print(f"Events: {events_path}")
    print(f"Summary: {summary_path}")
    return 1 if report["files_with_errors"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA))
    parser.add_argument("--out-dir", default=str(DEFAULT_VALIDATION_OUT))
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbols")
    parser.add_argument("--intervals", default="3,5", help="Comma-separated candle intervals, e.g. 3 or 3,5")
    args = parser.parse_args()
    intervals = tuple(int(value.strip()) for value in args.intervals.split(",") if value.strip())
    if not intervals or any(value not in (3, 5) for value in intervals):
        parser.error("--intervals must contain 3 and/or 5")
    symbols = [value for value in args.symbols.split(",") if value.strip()]
    raise SystemExit(run(args.data_dir, args.out_dir, intervals, symbols or None))


if __name__ == "__main__":
    main()
