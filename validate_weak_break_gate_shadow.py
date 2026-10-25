"""Shadow-only validation for weak-break reason combinations; never edits scanner or ledger."""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parent / "data" / "three_minute_shadow_replay_20261026_001138" / "shadow_candidates_outcomes.csv"
FEATURES = {
    "trend_weak": "Short-term trend alignment weak",
    "close_weak": "Weak candle close location",
    "vwap_conflict": "VWAP conflicts with direction",
    "body_weak": "Directional candle body weak or opposing",
}

def truth(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}

def number(value):
    try:
        n = float(str(value).strip())
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def parse_reasons(value):
    s = str(value or "").strip()
    if not s:
        return []
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return [str(x).strip() for x in obj if str(x).strip()]
        if isinstance(obj, str):
            s = obj
    except (ValueError, TypeError):
        pass
    if "||" in s:
        return [x.strip() for x in s.split("||") if x.strip()]
    if ";" in s:
        return [x.strip() for x in s.split(";") if x.strip()]
    return [s.strip("[]""'")]

def metric(rows):
    vals = [r["ret"] for r in rows if r["ret"] is not None]
    if not vals:
        return {"signals": 0, "positive_pct": None, "mean_return_pct": None, "median_return_pct": None}
    return {
        "signals": len(vals),
        "positive_pct": round(100 * sum(x > 0 for x in vals) / len(vals), 2),
        "mean_return_pct": round(statistics.fmean(vals), 6),
        "median_return_pct": round(statistics.median(vals), 6),
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output-dir", type=Path, default=None)
    p.add_argument("--fresh-after", default="2026-10-22",
                   help="Only dates strictly after this date count as fresh validation.")
    p.add_argument("--spacing-minutes", type=int, default=15)
    a = p.parse_args()
    if not a.input.is_file():
        p.error("input not found: " + str(a.input))
    if a.spacing_minutes < 0:
        p.error("spacing-minutes must be >= 0")
    fresh_after = date.fromisoformat(a.fresh_after)

    with a.input.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        raw = list(reader)
    needed = {"symbol", "date", "timestamp", "direction", "verdict", "close_return_percent",
              "horizon_complete", "reasons"}
    if needed - set(columns):
        p.error("missing columns: " + ", ".join(sorted(needed - set(columns))))

    parsed, malformed, incomplete = [], 0, 0
    for x in raw:
        try:
            ts = datetime.fromisoformat(str(x["timestamp"]).strip().replace("Z", "+00:00"))
            day = date.fromisoformat(str(x["date"]).strip()[:10])
            symbol = str(x["symbol"]).strip().upper()
            if not symbol:
                raise ValueError("blank symbol")
        except (ValueError, TypeError, KeyError):
            malformed += 1
            continue
        complete = truth(x.get("horizon_complete"))
        ret = number(x.get("close_return_percent"))
        if complete and ret is None:
            malformed += 1
            continue
        if not complete:
            incomplete += 1
        reasons = parse_reasons(x.get("reasons"))
        joined = " | ".join(reasons).lower()
        flags = {k: phrase.lower() in joined for k, phrase in FEATURES.items()}
        parsed.append({
            "symbol": symbol, "day": day, "ts": ts,
            "direction": str(x.get("direction", "")).strip().upper(),
            "verdict": str(x.get("verdict", "")).strip().upper(),
            "ret": ret if complete else None,
            "complete": complete,
            "reasons": reasons,
            "mfe": number(x.get("mfe_percent")),
            "mae": number(x.get("mae_percent")),
            "score": number(x.get("score")),
            **flags,
        })

    # Apply spacing to all structurally valid rows first, including incomplete outcomes.
    lanes = defaultdict(list)
    for r in parsed:
        lanes[(r["symbol"], r["day"])].append(r)
    spaced = []
    for lane in lanes.values():
        last = None
        for r in sorted(lane, key=lambda z: z["ts"]):
            if last is None or r["ts"] >= last + timedelta(minutes=a.spacing_minutes):
                spaced.append(r)
                last = r["ts"]

    eligible = [r for r in spaced if r["complete"] and r["ret"] is not None
                and r["direction"] == "BULLISH"]
    fresh = [r for r in eligible if r["day"] > fresh_after]
    historical = [r for r in eligible if date(2026, 10, 14) <= r["day"] < date(2026, 10, 23)]

    candidates = [
        ("Existing WATCH_WEAK_BREAK", lambda r: r["verdict"] == "WATCH_WEAK_BREAK"),
        ("Weak close AND VWAP conflict", lambda r: r["close_weak"] and r["vwap_conflict"]),
        ("Weak trend AND weak close AND VWAP conflict",
         lambda r: r["trend_weak"] and r["close_weak"] and r["vwap_conflict"]),
    ]

    def summarize(dataset, label):
        rows_out = []
        for name, predicate in candidates:
            excluded = [r for r in dataset if predicate(r)]
            kept = [r for r in dataset if not predicate(r)]
            base_m, ex_m, keep_m = metric(dataset), metric(excluded), metric(kept)
            day_changes = []
            for d in sorted({r["day"] for r in dataset}):
                day_rows = [r for r in dataset if r["day"] == d]
                day_kept = [r for r in day_rows if not predicate(r)]
                dm, km = metric(day_rows), metric(day_kept)
                if dm["mean_return_pct"] is not None and km["mean_return_pct"] is not None:
                    day_changes.append(km["mean_return_pct"] - dm["mean_return_pct"])
            rows_out.append({
                "dataset": label, "scenario": name, "baseline_signals": base_m["signals"],
                "excluded_signals": ex_m["signals"],
                "excluded_pct": round(100 * ex_m["signals"] / base_m["signals"], 2) if base_m["signals"] else None,
                "excluded_positive_pct": ex_m["positive_pct"],
                "excluded_mean_return_pct": ex_m["mean_return_pct"],
                "excluded_median_return_pct": ex_m["median_return_pct"],
                "remaining_signals": keep_m["signals"], "remaining_positive_pct": keep_m["positive_pct"],
                "remaining_mean_return_pct": keep_m["mean_return_pct"],
                "remaining_median_return_pct": keep_m["median_return_pct"],
                "mean_change_vs_baseline_pp": round(keep_m["mean_return_pct"] - base_m["mean_return_pct"], 6)
                    if keep_m["mean_return_pct"] is not None and base_m["mean_return_pct"] is not None else None,
                "dates_improved": sum(v > 0 for v in day_changes),
                "dates_worsened": sum(v < 0 for v in day_changes),
                "excluded_positive_signals_not_blocked_by_existing_gate": sum(
                    r["verdict"] != "WATCH_WEAK_BREAK" and r["ret"] > 0 for r in excluded),
                "note": "Underlying-stock returns only; descriptive and shadow-only, not causal proof or option P&L."
            })
        return rows_out

    summaries = summarize(historical, "previous_holdout_2026-10-14_to_2026-10-22")
    if fresh:
        summaries += summarize(fresh, "fresh_dates_after_" + fresh_after.isoformat())

    # Inspect the small set that the two-feature candidate would reject even though the existing gate kept it.
    inspect = [r for r in historical if r["close_weak"] and r["vwap_conflict"]
               and r["verdict"] != "WATCH_WEAK_BREAK"]
    inspect_rows = []
    for r in sorted(inspect, key=lambda z: (z["day"], z["symbol"], z["ts"])):
        inspect_rows.append({
            "date": r["day"].isoformat(), "timestamp": r["ts"].isoformat(), "symbol": r["symbol"],
            "direction": r["direction"], "verdict": r["verdict"], "close_return_percent": r["ret"],
            "mfe_percent": r["mfe"], "mae_percent": r["mae"], "score": r["score"],
            "trend_weak": r["trend_weak"], "close_weak": r["close_weak"],
            "vwap_conflict": r["vwap_conflict"], "body_weak": r["body_weak"],
            "reasons": " || ".join(r["reasons"]),
        })

    out = a.output_dir or a.input.parent
    out.mkdir(parents=True, exist_ok=True)
    for filename, data in [
        ("shadow_weak_break_fresh_validation.csv", summaries),
        ("shadow_weak_break_two_feature_retained_cases.csv", inspect_rows),
    ]:
        path = out / filename
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            fields = list(dict.fromkeys(k for row in data for k in row))
            if not fields:
                fields = ["status"]
                data = [{"status": "No rows available"}]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)

    meta = {
        "input": str(a.input.resolve()), "raw_rows": len(raw),
        "structurally_parsed_rows": len(parsed), "complete_rows": sum(r["complete"] for r in parsed),
        "incomplete_horizon_rows": incomplete, "malformed_rows": malformed, "spaced_rows": len(spaced),
        "historical_holdout_bullish_rows": len(historical), "fresh_after_exclusive": fresh_after.isoformat(),
        "fresh_bullish_rows": len(fresh), "fresh_dates": sorted({r["day"].isoformat() for r in fresh}),
        "two_feature_cases_retained_by_existing_gate": len(inspect_rows),
        "spacing_minutes": a.spacing_minutes, "feature_phrases": FEATURES,
        "note": "Spacing is applied before filtering incomplete outcomes, matching the prior corrected audit approach. No production or ledger changes."
    }
    (out / "shadow_weak_break_fresh_validation_metadata.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    print("=== SHADOW-ONLY FRESH VALIDATION ===")
    print(json.dumps(meta, indent=2))
    if fresh:
        for row in summaries:
            if row["dataset"].startswith("fresh_dates"):
                print(row)
    else:
        print("NO FRESH VALIDATION DATES FOUND after", fresh_after.isoformat())
        print("Do not treat the earlier holdout as fresh validation. Run this script again against a replay CSV containing newer complete dates.")
    print("=== TWO-FEATURE CASES RETAINED BY EXISTING GATE (inspect all rows in CSV) ===")
    for row in inspect_rows[:20]:
        print(row)
    print("Saved reports:", out)
    print("SHADOW ONLY: no production scanner or paper-trade ledger changes.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
