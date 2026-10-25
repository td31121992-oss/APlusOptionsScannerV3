"""One-go, read-only audit of WATCH_WEAK_BREAK in the 3-minute shadow replay.

This tool reads the existing candidate/outcome CSV only. It never imports the
production scanner, writes the paper-trade ledger, or authorizes trades.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parent / "data" / "three_minute_shadow_replay_20261026_001138" / "shadow_candidates_outcomes.csv"


def parse_date(value: str) -> date:
    return date.fromisoformat(str(value).strip()[:10])


def parse_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def metrics(rows: list[dict]) -> dict:
    values = [float(row["return_pct"]) for row in rows]
    if not values:
        return {"signals": 0, "positive_pct": None, "mean_pct": None, "median_pct": None, "_mean": None}
    return {
        "signals": len(values),
        "positive_pct": round(100 * sum(v > 0 for v in values) / len(values), 2),
        "mean_pct": round(statistics.fmean(values), 6),
        "median_pct": round(statistics.median(values), 6),
        "_mean": statistics.fmean(values),
    }


def public_metrics(label: str, rows: list[dict], baseline_mean: float | None = None) -> dict:
    m = metrics(rows)
    return {
        "scenario": label,
        "signals": m["signals"],
        "positive_pct": m["positive_pct"],
        "mean_return_pct": m["mean_pct"],
        "median_return_pct": m["median_pct"],
        "dates": len({r["day"] for r in rows}),
        "mean_change_vs_baseline_pp": None if baseline_mean is None or m["_mean"] is None else round(m["_mean"] - baseline_mean, 6),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="candidate/outcome CSV path")
    parser.add_argument("--output-dir", type=Path, default=None, help="where to save the separate audit reports")
    parser.add_argument("--start", default="2026-10-14", help="holdout start date inclusive, YYYY-MM-DD")
    parser.add_argument("--end-exclusive", default="2026-10-23", help="holdout end date exclusive, YYYY-MM-DD")
    parser.add_argument("--spacing-minutes", type=int, default=15)
    args = parser.parse_args()

    if args.spacing_minutes < 1:
        parser.error("--spacing-minutes must be at least 1")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end_exclusive)
    if end <= start:
        parser.error("--end-exclusive must be after --start")
    if not args.input.is_file():
        parser.error(f"input file not found: {args.input}")

    required = {"symbol", "date", "timestamp", "direction", "verdict", "close_return_percent", "horizon_complete"}
    with args.input.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            parser.error("missing required columns: " + ", ".join(sorted(missing)))
        raw = list(reader)

    parsed, invalid = [], 0
    for row in raw:
        try:
            ts = datetime.fromisoformat(str(row["timestamp"]).strip().replace("Z", "+00:00"))
            day = parse_date(row["date"])
            ret = float(row["close_return_percent"])
            symbol = str(row["symbol"]).strip().upper()
            if not symbol:
                raise ValueError("blank symbol")
            parsed.append({
                "symbol": symbol, "day": day, "timestamp": ts,
                "direction": str(row["direction"]).strip().upper(),
                "verdict": str(row["verdict"]).strip().upper(),
                "return_pct": ret,
                "complete": parse_bool(row["horizon_complete"]),
                "shadow_only": parse_bool(row.get("shadow_only", "")),
                "trade_authorized": parse_bool(row.get("trade_authorized", "")),
            })
        except (TypeError, ValueError, KeyError):
            invalid += 1

    # Rebuild spacing across all directions and verdicts before filtering the holdout.
    by_lane: dict[tuple[str, date], list[dict]] = defaultdict(list)
    for row in parsed:
        by_lane[(row["symbol"], row["day"])].append(row)
    spaced = []
    for lane_rows in by_lane.values():
        last_kept = None
        for row in sorted(lane_rows, key=lambda r: r["timestamp"]):
            ts = row["timestamp"]
            if last_kept is None or ts >= last_kept + timedelta(minutes=args.spacing_minutes):
                spaced.append(row)
                last_kept = ts

    test = [
        r for r in spaced
        if start <= r["day"] < end
        and r["direction"] == "BULLISH"
        and r["complete"]
    ]
    if not test:
        parser.error("no complete bullish holdout observations found for selected dates")

    baseline = list(test)
    kept = [r for r in test if r["verdict"] != "WATCH_WEAK_BREAK"]
    rejected = [r for r in test if r["verdict"] == "WATCH_WEAK_BREAK"]
    base_mean = metrics(baseline)["_mean"]
    summary = [
        public_metrics("Baseline", baseline),
        public_metrics("Gate scenario", kept, base_mean),
        public_metrics("Rejected WATCH_WEAK_BREAK", rejected, base_mean),
    ]

    daily = []
    for day in sorted({r["day"] for r in test}):
        b = [r for r in test if r["day"] == day]
        g = [r for r in b if r["verdict"] != "WATCH_WEAK_BREAK"]
        x = [r for r in b if r["verdict"] == "WATCH_WEAK_BREAK"]
        bm, gm = metrics(b), metrics(g)
        daily.append({
            "date": day.isoformat(), "baseline_signals": bm["signals"],
            "rejected_signals": len(x), "baseline_mean_pct": bm["mean_pct"],
            "gate_mean_pct": gm["mean_pct"],
            "mean_change_pp": None if gm["_mean"] is None else round(gm["_mean"] - bm["_mean"], 6),
            "baseline_positive_pct": bm["positive_pct"], "gate_positive_pct": gm["positive_pct"],
        })

    symbol_rows = []
    for symbol in sorted({r["symbol"] for r in test}):
        b = [r for r in test if r["symbol"] == symbol]
        x = [r for r in b if r["verdict"] == "WATCH_WEAK_BREAK"]
        if not x:
            continue
        g = [r for r in b if r["verdict"] != "WATCH_WEAK_BREAK"]
        bm, gm, xm = metrics(b), metrics(g), metrics(x)
        symbol_rows.append({
            "symbol": symbol, "baseline_signals": bm["signals"],
            "rejected_signals": xm["signals"], "rejected_positive_pct": xm["positive_pct"],
            "rejected_mean_pct": xm["mean_pct"], "baseline_mean_pct": bm["mean_pct"],
            "gate_mean_pct": gm["mean_pct"],
            "mean_change_pp": None if gm["_mean"] is None else round(gm["_mean"] - bm["_mean"], 6),
            "dates_with_rejected": len({r["day"] for r in x}),
        })

    out = args.output_dir or args.input.parent
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "summary": out / "shadow_weak_break_audit_summary.csv",
        "daily": out / "shadow_weak_break_audit_daily.csv",
        "symbols": out / "shadow_weak_break_audit_symbols.csv",
        "metadata": out / "shadow_weak_break_audit_metadata.json",
    }
    write_csv(paths["summary"], summary)
    write_csv(paths["daily"], daily)
    write_csv(paths["symbols"], symbol_rows)

    metadata = {
        "input": str(args.input.resolve()), "raw_rows": len(raw),
        "parsed_rows": len(parsed), "invalid_rows": invalid,
        "spaced_rows": len(spaced), "holdout_start_inclusive": start.isoformat(),
        "holdout_end_exclusive": end.isoformat(), "spacing_minutes": args.spacing_minutes,
        "complete_bullish_holdout_rows": len(test),
        "shadow_only_false_rows": sum(not r["shadow_only"] for r in test),
        "trade_authorized_true_rows": sum(r["trade_authorized"] for r in test),
        "dates_improved": sum((r["mean_change_pp"] or 0) > 0 for r in daily),
        "dates_worsened": sum((r["mean_change_pp"] or 0) < 0 for r in daily),
        "dates_unchanged": sum((r["mean_change_pp"] or 0) == 0 for r in daily),
        "symbols_with_rejected_signals": len(symbol_rows),
        "symbols_improved": sum((r["mean_change_pp"] or 0) > 0 for r in symbol_rows),
        "symbols_worsened": sum((r["mean_change_pp"] or 0) < 0 for r in symbol_rows),
        "note": "Underlying-stock returns only; not option P&L, and not a production recommendation.",
    }
    paths["metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\n=== SHADOW WEAK-BREAK AUDIT: DATA QUALITY ===")
    print(json.dumps(metadata, indent=2))
    print("\n=== OVERALL HOLDOUT METRICS ===")
    for row in summary:
        print(row)
    print("\n=== DAILY CONSISTENCY ===")
    for row in daily:
        print(row)
    print("\n=== TOP 20 SYMBOLS BY REJECTED SIGNAL COUNT ===")
    for row in sorted(symbol_rows, key=lambda r: r["rejected_signals"], reverse=True)[:20]:
        print(row)
    print("\n=== TOP 15 SYMBOLS BY POSITIVE MEAN CHANGE ===")
    for row in sorted(symbol_rows, key=lambda r: (r["mean_change_pp"] is not None, r["mean_change_pp"] or -1e99), reverse=True)[:15]:
        print(row)
    print("\n=== TOP 15 SYMBOLS BY NEGATIVE MEAN CHANGE ===")
    for row in sorted(symbol_rows, key=lambda r: (r["mean_change_pp"] is None, r["mean_change_pp"] if r["mean_change_pp"] is not None else 0))[:15]:
        print(row)
    print("\nSaved audit files:")
    for path in paths.values():
        print(path)
    print("\nSHADOW ONLY: read-only input; separate reports only; no production or paper-trade ledger changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
