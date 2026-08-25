from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default

def parse_ts(s):
    try:
        return datetime.fromisoformat(str(s))
    except Exception:
        return None

def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

def canonicalize_per_minute(rows):
    """One row per symbol/minute. Prefer richer row, then latest timestamp."""
    best = {}
    for r in rows:
        ts = parse_ts(r.get("snapshot_time"))
        if ts is None:
            continue
        sym = str(r.get("symbol","")).upper().strip()
        if not sym:
            continue
        minute = ts.replace(second=0, microsecond=0)
        richness = sum(1 for k,v in r.items() if v not in ("",None))
        key = (sym, minute)
        old = best.get(key)
        rank = (richness, ts)
        if old is None or rank > old[0]:
            rr = dict(r)
            rr["_ts"] = ts
            rr["_minute"] = minute
            best[key] = (rank, rr)
    out = defaultdict(list)
    for (_, _), (_, r) in best.items():
        out[r["symbol"]].append(r)
    for arr in out.values():
        arr.sort(key=lambda x: x["_minute"])
    return out

def direction_sign(r):
    d = str(r.get("direction","")).upper()
    return -1.0 if d == "BEARISH" else 1.0

def is_vwap_aligned(r):
    d = str(r.get("direction","")).upper()
    v = num(r.get("vwap_distance_pct"), 0.0) or 0.0
    if d == "BEARISH":
        return v <= 0
    if d == "BULLISH":
        return v >= 0
    return True

def persistence_confirmation(arr, start_idx, window=3, min_aplus=2,
                             max_chase=35.0, min_clean=65.0, min_trend=40.0):
    """Require a persistent, direction-consistent confirmation window."""
    if start_idx + window > len(arr):
        return None
    w = arr[start_idx:start_idx+window]

    # Ensure observations are close enough in time to be a real persistence run.
    for a,b in zip(w, w[1:]):
        if (b["_minute"] - a["_minute"]).total_seconds() > 180:
            return None

    dirs = [str(x.get("direction","")).upper() for x in w]
    dirs2 = [x for x in dirs if x in ("BULLISH","BEARISH")]
    if dirs2 and len(set(dirs2)) != 1:
        return None

    scores = [num(x.get("chart_score"),0.0) or 0.0 for x in w]
    if min(scores) < 75:
        return None
    if sum(s >= 85 for s in scores) < min_aplus:
        return None

    if not all(is_vwap_aligned(x) for x in w):
        return None

    clean = [num(x.get("clean_trend"),0.0) or 0.0 for x in w]
    trend = [num(x.get("trend_alignment"),0.0) or 0.0 for x in w]
    chase = [num(x.get("chase_risk"),0.0) or 0.0 for x in w]
    if max(clean) < min_clean:
        return None
    if max(trend) < min_trend:
        return None
    if max(chase) > max_chase:
        return None

    # Prefer rising/holding quality: final score must not collapse vs first.
    if scores[-1] < scores[0] - 5:
        return None

    return w[-1]

def closest_forward(arr, detect_idx, minutes, max_lag=4):
    target = arr[detect_idx]["_minute"] + timedelta(minutes=minutes)
    best = None
    for j in range(detect_idx+1, len(arr)):
        t = arr[j]["_minute"]
        if t < target:
            continue
        lag = (t-target).total_seconds()/60
        if lag > max_lag:
            break
        best = arr[j]
        break
    return best

def main():
    ap = argparse.ArgumentParser(description="APlus Chart Engine V3 persistence and false-positive test")
    ap.add_argument("--day", default="2026-08-20")
    ap.add_argument("--input-root", default="data/chart_engine_research_v2")
    ap.add_argument("--output-root", default="data/chart_engine_research_v3")
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--min-aplus", type=int, default=2)
    ap.add_argument("--winner-threshold", type=float, default=2.0)
    args = ap.parse_args()

    src = ROOT / args.input_root / args.day / "full_market_timeline.csv"
    if not src.is_file():
        raise SystemExit(f"Missing V2 timeline: {src}")

    rows = read_csv(src)
    bysym = canonicalize_per_minute(rows)
    outdir = ROOT / args.output_root / args.day
    outdir.mkdir(parents=True, exist_ok=True)

    detections = []
    summaries = []

    for sym, arr in sorted(bysym.items()):
        # Exact threshold first-times: fixes V2 "A+ before STRONG" reporting issue.
        first_strong = next((x for x in arr if (num(x.get("chart_score"),0) or 0) >= 75), None)
        first_aplus = next((x for x in arr if (num(x.get("chart_score"),0) or 0) >= 85), None)

        confirmed = None
        confirmed_idx = None
        for i in range(len(arr)):
            c = persistence_confirmation(
                arr, i, window=args.window, min_aplus=args.min_aplus
            )
            if c is not None:
                confirmed = c
                confirmed_idx = arr.index(c)
                break

        last_fop = next((num(x.get("from_open_pct")) for x in reversed(arr)
                         if num(x.get("from_open_pct")) is not None), None)
        cohort = (
            "BIG_MOVER" if last_fop is not None and abs(last_fop) >= args.winner_threshold
            else "CONTROL" if last_fop is not None
            else "NO_EOD_DATA"
        )

        detrow = {}
        if confirmed is not None:
            sign = direction_sign(confirmed)
            base = num(confirmed.get("from_open_pct"), 0.0) or 0.0
            detrow = {
                "symbol": sym,
                "detection_time": confirmed["_minute"].isoformat(),
                "direction": confirmed.get("direction",""),
                "chart_score": num(confirmed.get("chart_score"),0),
                "quality": num(confirmed.get("quality"),0),
                "clean_trend": num(confirmed.get("clean_trend"),0),
                "trend_alignment": num(confirmed.get("trend_alignment"),0),
                "relative_volume": num(confirmed.get("relative_volume"),0),
                "vwap_distance_pct": num(confirmed.get("vwap_distance_pct"),0),
                "chase_risk": num(confirmed.get("chase_risk"),0),
                "from_open_at_detection": base,
                "cohort": cohort,
            }
            for mins in (5,15,30,60):
                fw = closest_forward(arr, confirmed_idx, mins)
                if fw is None:
                    detrow[f"fwd_{mins}m_pp"] = ""
                    detrow[f"fwd_{mins}m_positive"] = ""
                else:
                    future = num(fw.get("from_open_pct"))
                    if future is None:
                        detrow[f"fwd_{mins}m_pp"] = ""
                        detrow[f"fwd_{mins}m_positive"] = ""
                    else:
                        delta = round((future-base)*sign, 4)
                        detrow[f"fwd_{mins}m_pp"] = delta
                        detrow[f"fwd_{mins}m_positive"] = delta > 0
            detections.append(detrow)

        summaries.append({
            "symbol": sym,
            "minutes_seen": len(arr),
            "first_strong": first_strong["_minute"].isoformat() if first_strong else "",
            "first_a_plus": first_aplus["_minute"].isoformat() if first_aplus else "",
            "confirmed_v3": confirmed is not None,
            "confirmation_time": confirmed["_minute"].isoformat() if confirmed else "",
            "confirmation_score": num(confirmed.get("chart_score"),0) if confirmed else "",
            "eod_from_open_pct": last_fop if last_fop is not None else "",
            "cohort": cohort,
        })

    write_csv(outdir/"v3_detections.csv", detections)
    write_csv(outdir/"v3_symbol_summary.csv", summaries)

    cohort_rows = []
    for cohort in ("BIG_MOVER","CONTROL"):
        ss = [x for x in summaries if x["cohort"] == cohort]
        dd = [x for x in detections if x["cohort"] == cohort]
        if not ss:
            continue
        row = {
            "cohort": cohort,
            "symbols": len(ss),
            "v3_confirmed": len(dd),
            "v3_confirmed_pct": round(100*len(dd)/len(ss),2),
        }
        for mins in (5,15,30,60):
            vals = [num(x.get(f"fwd_{mins}m_pp")) for x in dd]
            vals = [v for v in vals if v is not None]
            row[f"avg_fwd_{mins}m_pp"] = round(sum(vals)/len(vals),4) if vals else ""
            row[f"winrate_{mins}m_pct"] = round(100*sum(v>0 for v in vals)/len(vals),2) if vals else ""
        cohort_rows.append(row)

    write_csv(outdir/"v3_cohort_comparison.csv", cohort_rows)

    # False positives = control symbols that passed V3.
    false_pos = sorted(
        [x for x in detections if x["cohort"]=="CONTROL"],
        key=lambda x:(num(x.get("chart_score"),0), num(x.get("fwd_30m_pp"),-999)),
        reverse=True
    )
    write_csv(outdir/"v3_false_positives.csv", false_pos)

    # True positives = big movers that passed V3.
    true_pos = sorted(
        [x for x in detections if x["cohort"]=="BIG_MOVER"],
        key=lambda x:num(x.get("chart_score"),0),
        reverse=True
    )
    write_csv(outdir/"v3_true_positives.csv", true_pos)

    manifest = {
        "mode":"READ_ONLY_PERSISTENCE_CONFIRMATION",
        "day":args.day,
        "symbols":len(bysym),
        "persistence_window_minutes":args.window,
        "minimum_a_plus_minutes_in_window":args.min_aplus,
        "requirements":{
            "all_window_scores_at_least":75,
            "at_least_n_a_plus_scores":args.min_aplus,
            "vwap_alignment_all_minutes":True,
            "max_chase_risk":35,
            "minimum_clean_trend_seen":65,
            "minimum_trend_alignment_seen":40,
            "score_collapse_tolerance_points":5,
        },
        "forward_measure":"direction-adjusted change in persisted from-open percentage points; not option P&L",
        "dhan_api_calls":0,
        "production_files_modified":False,
    }
    (outdir/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    print("="*108)
    print("APLUS CHART ENGINE V3 - PERSISTENCE & FALSE-POSITIVE TEST")
    print("READ ONLY - NO DHAN CALLS - NO PRODUCTION CHANGES")
    print("="*108)
    print("Day                 :", args.day)
    print("Symbols analysed    :", len(bysym))
    print("V3 confirmations    :", len(detections))
    print("Persistence rule    :", f"{args.window} minutes, >= {args.min_aplus} A+ observations")
    print("")
    print("COHORT RESULTS")
    for r in cohort_rows:
        print(
            f"{r['cohort']:<10} symbols={r['symbols']:<4} "
            f"confirmed={r['v3_confirmed']:<4} ({r['v3_confirmed_pct']:>6.2f}%) "
            f"15m_win={str(r.get('winrate_15m_pct','')):>6}% "
            f"30m_win={str(r.get('winrate_30m_pct','')):>6}% "
            f"60m_win={str(r.get('winrate_60m_pct','')):>6}%"
        )
    print("")
    print("KEY CASES")
    for sym in ("COFORGE","MCX","SBICARD","MOTILALOFS","PREMIERENE","GLENMARK"):
        s = next((x for x in summaries if x["symbol"]==sym), None)
        d = next((x for x in detections if x["symbol"]==sym), None)
        if s:
            print(
                f"{sym:<12} strong={str(s['first_strong'])[11:16] if s['first_strong'] else '-':<5} "
                f"A+={str(s['first_a_plus'])[11:16] if s['first_a_plus'] else '-':<5} "
                f"V3={str(s['confirmation_time'])[11:16] if s['confirmation_time'] else '-':<5} "
                f"30m={d.get('fwd_30m_pp','') if d else ''} "
                f"60m={d.get('fwd_60m_pp','') if d else ''}"
            )
    print("")
    print("Files:")
    print("  v3_detections.csv")
    print("  v3_symbol_summary.csv")
    print("  v3_cohort_comparison.csv")
    print("  v3_true_positives.csv")
    print("  v3_false_positives.csv")
    print("  run_manifest.json")
    print("="*108)

if __name__=="__main__":
    main()
