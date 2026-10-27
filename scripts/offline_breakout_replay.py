"""Offline, read-only OHLCV breakout replay. No broker calls or order placement."""
import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "upstox_market_data"
DEFAULT_OUT = ROOT / "data" / "research_replay"
HORIZONS = (5, 10, 15)
LOOKBACK = 20
VOLUME_MULTIPLE = 1.5


def parse_time(value):
    value = (value or "").strip()
    if not value:
        raise ValueError("empty timestamp")
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def load_candles(path):
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("missing CSV header")
        fields = {name.strip().lower(): name for name in reader.fieldnames}
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = sorted(required - fields.keys())
        if missing:
            raise ValueError("missing columns: " + ", ".join(missing))
        candles = []
        for line_number, row in enumerate(reader, start=2):
            try:
                candle = {
                    "timestamp": parse_time(row[fields["timestamp"]]),
                    "open": float(row[fields["open"]]),
                    "high": float(row[fields["high"]]),
                    "low": float(row[fields["low"]]),
                    "close": float(row[fields["close"]]),
                    "volume": float(row[fields["volume"]]),
                }
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"line {line_number}: invalid candle ({exc})") from exc
            o, h, low, close, volume = (
                candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]
            )
            if min(o, h, low, close) <= 0 or h < max(o, close, low) or low > min(o, close, h) or volume < 0:
                raise ValueError(f"line {line_number}: invalid OHLC/volume values")
            candles.append(candle)
    candles.sort(key=lambda candle: candle["timestamp"])
    seen = set()
    for candle in candles:
        stamp = candle["timestamp"].isoformat()
        if stamp in seen:
            raise ValueError(f"duplicate timestamp: {stamp}")
        seen.add(stamp)
    return candles


def session_key(candle):
    # Group by the timestamp's own date. Upstox timestamps may be UTC; this is
    # deliberately a conservative boundary, not an exchange-time conversion.
    return candle["timestamp"].date().isoformat()


def find_signals(candles, symbol, interval, lookback=LOOKBACK, volume_multiple=VOLUME_MULTIPLE):
    sessions = defaultdict(list)
    for candle in candles:
        sessions[session_key(candle)].append(candle)
    signals = []
    for day, bars in sorted(sessions.items()):
        for i in range(lookback + 1, len(bars)):
            history = bars[i-lookback:i]
            prior_history = bars[i-lookback-1:i-1]
            bar = bars[i]
            previous = bars[i-1]
            prior_high = max(c["high"] for c in history)
            prior_low = min(c["low"] for c in history)
            previous_high = max(c["high"] for c in prior_history)
            previous_low = min(c["low"] for c in prior_history)
            baseline_volume = mean(c["volume"] for c in history)
            ratio = (bar["volume"] / baseline_volume) if baseline_volume > 0 else None
            side = None
            if bar["close"] > prior_high and previous["close"] <= previous_high:
                side = "LONG_BREAKOUT"
            elif bar["close"] < prior_low and previous["close"] >= previous_low:
                side = "SHORT_BREAKDOWN"
            if not side:
                continue
            signals.append({
                "symbol": symbol, "interval_minutes": interval, "session_date": day,
                "timestamp": bar["timestamp"].isoformat(), "side": side,
                "entry_reference_close": bar["close"], "prior_20_high": prior_high,
                "prior_20_low": prior_low, "volume": bar["volume"],
                "prior_20_avg_volume": baseline_volume, "volume_ratio": ratio,
                "volume_confirmed": bool(ratio is not None and ratio >= volume_multiple),
                "_bars": bars, "_index": i,
            })
    return signals


def evaluate_signal(signal, horizon):
    bars, index = signal["_bars"], signal["_index"]
    future = bars[index+1:index+1+horizon]
    if len(future) != horizon:
        return None
    entry = signal["entry_reference_close"]
    side = signal["side"]
    if side == "LONG_BREAKOUT":
        mfe = (max(c["high"] for c in future) / entry - 1) * 100
        mae = (min(c["low"] for c in future) / entry - 1) * 100
        exit_return = (future[-1]["close"] / entry - 1) * 100
    else:
        mfe = (entry / min(c["low"] for c in future) - 1) * 100
        mae = (entry / max(c["high"] for c in future) - 1) * 100
        exit_return = (entry / future[-1]["close"] - 1) * 100
    return {
        "horizon_bars": horizon, "exit_timestamp": future[-1]["timestamp"].isoformat(),
        "exit_close": future[-1]["close"], "directional_return_pct": exit_return,
        "mfe_pct": mfe, "mae_pct": mae,
        "positive_at_horizon": exit_return > 0,
    }


def summarize(rows):
    if not rows:
        return {"n": 0}
    returns = [row["directional_return_pct"] for row in rows]
    mfes = [row["mfe_pct"] for row in rows]
    maes = [row["mae_pct"] for row in rows]
    return {
        "n": len(rows),
        "positive_at_horizon_pct": round(100 * sum(value > 0 for value in returns) / len(returns), 2),
        "mean_directional_return_pct": round(mean(returns), 4),
        "median_directional_return_pct": round(sorted(returns)[len(returns)//2], 4),
        "mean_mfe_pct": round(mean(mfes), 4),
        "mean_mae_pct": round(mean(maes), 4),
    }


def run(data_dir=DEFAULT_DATA, out_dir=DEFAULT_OUT, symbols=None, intervals=(3, 5)):
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    files = []
    for interval in intervals:
        files.extend(sorted(data_dir.glob(f"*_{interval}m.csv")))
    if symbols:
        allow = {symbol.strip().upper() for symbol in symbols}
        files = [path for path in files if path.stem.rsplit("_", 1)[0].upper() in allow]
    if not files:
        raise RuntimeError(f"No matching candle CSVs found under {data_dir}")
    all_rows, quality = [], []
    for path in files:
        symbol, interval_text = path.stem.rsplit("_", 1)
        interval = int(interval_text[:-1])
        try:
            candles = load_candles(path)
            signals = find_signals(candles, symbol, interval)
            evaluated_count = 0
            for signal in signals:
                for horizon in HORIZONS:
                    outcome = evaluate_signal(signal, horizon)
                    row = {key: value for key, value in signal.items() if not key.startswith("_")}
                    row.update({"horizon_bars": horizon, "horizon_minutes": horizon * interval})
                    if outcome:
                        row.update(outcome)
                        row["outcome_available"] = True
                        evaluated_count += 1
                    else:
                        row.update({"exit_timestamp": "", "exit_close": "", "directional_return_pct": "",
                                    "mfe_pct": "", "mae_pct": "", "positive_at_horizon": "",
                                    "outcome_available": False})
                    all_rows.append(row)
            sessions = len({session_key(c) for c in candles})
            quality.append({"file": path.name, "symbol": symbol, "interval_minutes": interval,
                            "status": "ok", "candles": len(candles), "sessions": sessions,
                            "signals": len(signals), "outcomes_available": evaluated_count})
        except Exception as exc:
            quality.append({"file": path.name, "symbol": symbol, "interval_minutes": interval,
                            "status": "error", "error": str(exc)})
    out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = out_dir / "breakout_replay_events.csv"
    columns = [
        "symbol", "interval_minutes", "session_date", "timestamp", "side",
        "entry_reference_close", "prior_20_high", "prior_20_low", "volume",
        "prior_20_avg_volume", "volume_ratio", "volume_confirmed",
        "horizon_bars", "horizon_minutes", "exit_timestamp", "exit_close",
        "directional_return_pct", "mfe_pct", "mae_pct", "positive_at_horizon", "outcome_available",
    ]
    with detail_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    summaries = []
    for interval in intervals:
        for horizon in HORIZONS:
            for side in ("LONG_BREAKOUT", "SHORT_BREAKDOWN"):
                for confirmed in (False, True):
                    group = [r for r in all_rows if r["interval_minutes"] == interval
                             and r["horizon_bars"] == horizon and r["side"] == side
                             and r["volume_confirmed"] is confirmed and r["outcome_available"]]
                    item = {"interval_minutes": interval, "horizon_bars": horizon,
                            "horizon_minutes": horizon * interval, "side": side,
                            "volume_confirmed": confirmed}
                    item.update(summarize(group))
                    summaries.append(item)
    summary_path = out_dir / "breakout_replay_summary.json"
    report = {
        "mode": "offline_read_only_historical_research",
        "source": "local Upstox historical OHLCV CSVs",
        "lookback_bars": LOOKBACK, "volume_confirmation_multiple": VOLUME_MULTIPLE,
        "horizons_bars": list(HORIZONS),
        "input_files": len(files),
        "files_ok": sum(item["status"] == "ok" for item in quality),
        "files_with_errors": [item for item in quality if item["status"] != "ok"],
        "candles": sum(item.get("candles", 0) for item in quality),
        "signals": sum(item.get("signals", 0) for item in quality),
        "event_rows": len(all_rows),
        "available_outcomes": sum(bool(row["outcome_available"]) for row in all_rows),
        "limitations": [
            "Underlying price returns only; not option premium P&L.",
            "OHLCV does not contain true bid/ask-at-price footprint or aggressor-side flow.",
            "No slippage, fees, spread, execution delay, or position sizing model.",
            "Signals use a 20-bar prior range and current candle close; this is a research baseline, not the live scanner strategy.",
            "Future horizons are restricted to bars on the same timestamp-date group; verify timezone/session boundaries before interpreting results.",
            "Historical associations do not establish predictive edge or future profitability."
        ],
        "summary": summaries, "file_quality": quality,
    }
    summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Input files: {len(files)}; valid: {report['files_ok']}; errors: {len(report['files_with_errors'])}")
    print(f"Candles: {report['candles']}; signals: {report['signals']}; complete outcomes: {report['available_outcomes']}")
    print(f"Events: {detail_path}")
    print(f"Summary: {summary_path}")
    return 1 if report["files_with_errors"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol list")
    parser.add_argument("--intervals", default="3,5", help="Comma-separated candle intervals, e.g. 3 or 3,5")
    args = parser.parse_args()
    intervals = tuple(int(value.strip()) for value in args.intervals.split(",") if value.strip())
    if not intervals or any(value not in (3, 5) for value in intervals):
        parser.error("--intervals must contain 3 and/or 5")
    symbols = [value for value in args.symbols.split(",") if value.strip()]
    raise SystemExit(run(args.data_dir, args.out_dir, symbols or None, intervals))


if __name__ == "__main__":
    main()
