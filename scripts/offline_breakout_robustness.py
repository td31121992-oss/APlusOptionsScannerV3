"""Offline robustness audit for breakout validation events; never places orders."""
import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS = ROOT / "data" / "research_replay" / "validation" / "breakout_validation_events.csv"
DEFAULT_OUT = ROOT / "data" / "research_replay" / "validation" / "breakout_robustness_report.json"
CANDIDATES = (
    (3, "SHORT_BREAKDOWN", 15, "baseline"),
    (3, "SHORT_BREAKDOWN", 15, "volume_and_trend"),
    (3, "SHORT_BREAKDOWN", 15, "pullback_entry"),
    (5, "SHORT_BREAKDOWN", 15, "baseline"),
    (5, "SHORT_BREAKDOWN", 15, "volume_confirmed"),
    (5, "SHORT_BREAKDOWN", 15, "trend_aligned"),
    (5, "SHORT_BREAKDOWN", 15, "pullback_entry"),
)


def parse_timestamp(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def comparable_timestamps(left, right):
    """Only compare timestamps when both have the same timezone-awareness."""
    if left is None or right is None:
        return False
    return (left.tzinfo is None) == (right.tzinfo is None)


def load_events(path):
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"symbol", "interval_minutes", "session_date", "split", "side",
                "filter_variant", "horizon_bars", "outcome_available",
                "non_overlapping", "directional_return_pct", "signal_timestamp",
                "entry_timestamp", "exit_timestamp"}
    if rows and not required.issubset(rows[0]):
        raise ValueError("Events CSV missing columns: " + ", ".join(sorted(required - set(rows[0]))))
    return rows


def yes(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def summarize(rows):
    returns = [float(row["directional_return_pct"]) for row in rows
               if row.get("directional_return_pct") not in ("", None)]
    if not returns:
        return {"n": 0}
    winners = [value for value in returns if value > 0]
    total_positive = sum(winners)
    top_winners = sorted(winners, reverse=True)
    mfe_values = [float(r["mfe_pct"]) for r in rows if r.get("mfe_pct") not in ("", None)]
    mae_values = [float(r["mae_pct"]) for r in rows if r.get("mae_pct") not in ("", None)]
    return {
        "n": len(returns),
        "positive_pct": round(100 * len(winners) / len(returns), 2),
        "mean_return_pct": round(mean(returns), 5),
        "median_return_pct": round(median(returns), 5),
        "mean_mfe_pct": round(mean(mfe_values), 5) if mfe_values else None,
        "mean_mae_pct": round(mean(mae_values), 5) if mae_values else None,
        "top_1_winner_share_of_positive_returns_pct": round(100 * top_winners[0] / total_positive, 2) if total_positive > 0 else None,
        "top_5_winners_share_of_positive_returns_pct": round(100 * sum(top_winners[:5]) / total_positive, 2) if total_positive > 0 else None,
        "positive_return_sum_pct": round(total_positive, 5),
        "negative_return_sum_pct": round(sum(v for v in returns if v < 0), 5),
    }


def build_report(rows):
    complete = [r for r in rows if yes(r.get("outcome_available")) and r.get("directional_return_pct") not in ("", None)]
    test_spaced = [r for r in complete if r.get("split") == "test" and yes(r.get("non_overlapping"))]
    train_spaced = [r for r in complete if r.get("split") == "train" and yes(r.get("non_overlapping"))]
    candidate_reports = []
    for interval, side, horizon, variant in CANDIDATES:
        groups = {}
        for split, source in (("train", train_spaced), ("test", test_spaced)):
            group = [r for r in source if int(r["interval_minutes"]) == interval and r["side"] == side
                     and int(r["horizon_bars"]) == horizon and r["filter_variant"] == variant]
            groups[split] = summarize(group)
        test_group = [r for r in test_spaced if int(r["interval_minutes"]) == interval and r["side"] == side
                      and int(r["horizon_bars"]) == horizon and r["filter_variant"] == variant]
        by_symbol, by_session = defaultdict(list), defaultdict(list)
        for row in test_group:
            by_symbol[row["symbol"]].append(row)
            by_session[row["session_date"]].append(row)
        symbol_rows = [{"symbol": symbol, **summarize(group)} for symbol, group in by_symbol.items()]
        session_stats = [summarize(group) for group in by_session.values()]
        candidate_reports.append({
            "interval_minutes": interval, "side": side, "horizon_bars": horizon,
            "filter_variant": variant, "train": groups["train"], "test": groups["test"],
            "test_symbols": len(by_symbol), "test_sessions": len(by_session),
            "symbols_positive_mean": sum(1 for item in symbol_rows if item["mean_return_pct"] > 0),
            "symbols_negative_mean": sum(1 for item in symbol_rows if item["mean_return_pct"] < 0),
            "best_symbols": sorted(symbol_rows, key=lambda x: x["mean_return_pct"], reverse=True)[:10],
            "worst_symbols": sorted(symbol_rows, key=lambda x: x["mean_return_pct"])[:10],
            "positive_sessions": sum(1 for item in session_stats if item.get("mean_return_pct", 0) > 0),
            "negative_sessions": sum(1 for item in session_stats if item.get("mean_return_pct", 0) < 0),
            "top_winner_concentration": {
                "top_1_share_pct": groups["test"].get("top_1_winner_share_of_positive_returns_pct"),
                "top_5_share_pct": groups["test"].get("top_5_winners_share_of_positive_returns_pct"),
            },
        })

    stamps, offsets, naive = [], set(), 0
    invalid_order = 0
    incomparable_order_checks = 0
    session_counts = defaultdict(int)
    for row in rows:
        for field in ("signal_timestamp", "entry_timestamp", "exit_timestamp"):
            stamp = parse_timestamp(row.get(field, ""))
            if stamp is not None:
                stamps.append(stamp)
                if stamp.tzinfo is None:
                    naive += 1
                else:
                    offsets.add(str(stamp.utcoffset()))
        if row.get("session_date"):
            session_counts[row["session_date"]] += 1
        signal = parse_timestamp(row.get("signal_timestamp", ""))
        entry = parse_timestamp(row.get("entry_timestamp", ""))
        exit_ = parse_timestamp(row.get("exit_timestamp", ""))
        if signal and entry:
            if comparable_timestamps(signal, entry):
                if entry < signal:
                    invalid_order += 1
            else:
                incomparable_order_checks += 1
        if entry and exit_:
            if comparable_timestamps(entry, exit_):
                if exit_ <= entry:
                    invalid_order += 1
            else:
                incomparable_order_checks += 1
    dates = sorted(session_counts)
    session_gaps = []
    # Calendar gaps are for review only; weekends and exchange holidays are not classified.
    for left, right in zip(dates, dates[1:]):
        delta = (datetime.fromisoformat(right) - datetime.fromisoformat(left)).days
        if delta > 1:
            session_gaps.append({"from": left, "to": right, "calendar_days_apart": delta})
    return {
        "mode": "offline_read_only_robustness_audit",
        "input_event_rows": len(rows),
        "complete_outcomes": len(complete),
        "train_non_overlapping_outcomes": len(train_spaced),
        "test_non_overlapping_outcomes": len(test_spaced),
        "timestamp_audit": {
            "timestamp_values_checked": len(stamps),
            "naive_timestamp_values": naive,
            "explicit_utc_offsets_seen": sorted(offsets),
            "mixed_naive_and_offset_aware": bool(naive and offsets),
            "invalid_signal_entry_exit_order_count": invalid_order,
            "incomparable_timezone_order_checks_skipped": incomparable_order_checks,
            "session_dates_seen": len(dates),
            "first_session_date": dates[0] if dates else None,
            "last_session_date": dates[-1] if dates else None,
            "calendar_date_gaps_to_review": session_gaps,
            "warning": "This audit cannot establish NSE exchange-session completeness or timezone correctness without comparing timestamps against the source API and expected market calendar.",
        },
        "candidate_results": candidate_reports,
        "limitations": [
            "Underlying directional returns are not options P&L and ignore costs, spreads, slippage and fill mechanics.",
            "Symbols and sessions are correlated; symbol/session counts are diagnostics, not independent statistical trials.",
            "Top-winner contribution uses positive underlying percentage returns, not portfolio profit attribution.",
            "Pullback entries occur after the original signal and must be evaluated as a distinct entry rule.",
            "Timezone-incomparable timestamp pairs are flagged by the audit and excluded from ordering comparisons.",
            "This script does not modify scanner, broker, order, paper journal, or risk settings.",
        ],
    }


def run(events_path=DEFAULT_EVENTS, out_path=DEFAULT_OUT):
    rows = load_events(events_path)
    report = build_report(rows)
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Event rows: {report['input_event_rows']}; complete outcomes: {report['complete_outcomes']}")
    print(f"Train non-overlap: {report['train_non_overlapping_outcomes']}; test non-overlap: {report['test_non_overlapping_outcomes']}")
    print(f"Report: {output}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    run(args.events, args.out)


if __name__ == "__main__":
    main()
