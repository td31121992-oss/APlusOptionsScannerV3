from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"

DEFAULT_SYMBOLS = [
    "MCX","GLENMARK","SBICARD","PREMIERENE","MOTILALOFS"
]

PREFERRED_FIELDS = [
    "symbol","timestamp","stage","selection_tier","setup_family","direction",
    "score","trade_quality_score","movement_capture_score","trend_alignment_score",
    "clean_trend_score","chase_risk_score","relative_volume","vwap_distance_percent",
    "recent_move_5m_percent","recent_move_15m_percent","move_from_0915_open_percent",
    "from_open_pct","ema9","ema20","ema50","rsi","rsi14","adx","atr","atr14",
    "fresh_high","fresh_low","opening_range_breakout","opening_range_breakdown",
    "volume_acceleration","recent_volume_acceleration","range_position_percent",
]

ALIASES = {
    "from_open_pct": ["from_open_pct","move_from_0915_open_percent","from_0915_open_percent"],
    "recent_5m": ["recent_move_5m_percent","recent_move_5m_pct"],
    "recent_15m": ["recent_move_15m_percent","recent_move_15m_pct"],
    "rv": ["relative_volume","relative_volume_ratio","rvol"],
    "vwap_dist": ["vwap_distance_percent","vwap_distance_pct","distance_from_vwap_percent"],
    "trend": ["trend_alignment_score","trend_score"],
    "clean": ["clean_trend_score"],
    "capture": ["movement_capture_score"],
    "quality": ["trade_quality_score","score"],
    "chase": ["chase_risk_score"],
}

def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default

def _first_num(d, keys, default=None):
    for k in keys:
        if k in d:
            v = _num(d.get(k))
            if v is not None:
                return v
    return default

def _boolish(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int,float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1","true","yes","y","bullish","breakout"}
    return False

def discover_files(day: str):
    pat1 = f"intraday_movement_{day.replace('-','')}_" 
    pat2 = f"opening_momentum_{day.replace('-','')}_"
    files = []
    for p in REPORTS.glob("*.json"):
        n = p.name
        if n.startswith(pat1) or n.startswith(pat2):
            files.append(p)
    return sorted(files, key=lambda p: p.name)

def walk_rows(obj: Any):
    """Yield dicts that look like candidate rows, recursively."""
    if isinstance(obj, dict):
        if "symbol" in obj and any(k in obj for k in (
            "stage","direction","score","trade_quality_score","movement_capture_score",
            "relative_volume","vwap_distance_percent","from_open_pct","move_from_0915_open_percent"
        )):
            yield obj
        for v in obj.values():
            yield from walk_rows(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from walk_rows(x)

def infer_timestamp(path: Path, obj: dict):
    for k in ("generated_at","timestamp","as_of","created_at"):
        v = obj.get(k)
        if isinstance(v, str) and v:
            return v
    m = re.search(r"_(\d{8})_(\d{6})\.json$", path.name)
    if m:
        d,t = m.groups()
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}+05:30"
    return ""

def chart_score(r: dict):
    # Research-only composite using fields already persisted in scanner snapshots.
    from_open = abs(_first_num(r, ALIASES["from_open_pct"], 0.0) or 0.0)
    rv = _first_num(r, ALIASES["rv"], 0.0) or 0.0
    vwap = abs(_first_num(r, ALIASES["vwap_dist"], 0.0) or 0.0)
    trend = _first_num(r, ALIASES["trend"], 0.0) or 0.0
    clean = _first_num(r, ALIASES["clean"], 0.0) or 0.0
    capture = _first_num(r, ALIASES["capture"], 0.0) or 0.0
    quality = _first_num(r, ALIASES["quality"], 0.0) or 0.0
    chase = _first_num(r, ALIASES["chase"], 0.0) or 0.0
    r5 = abs(_first_num(r, ALIASES["recent_5m"], 0.0) or 0.0)
    r15 = abs(_first_num(r, ALIASES["recent_15m"], 0.0) or 0.0)

    score = 0.0
    score += min(from_open / 2.5, 1.0) * 12
    score += min(rv / 2.0, 1.0) * 12
    score += min(vwap / 1.0, 1.0) * 8
    score += min(trend / 80.0, 1.0) * 16
    score += min(clean / 80.0, 1.0) * 16
    score += min(capture / 75.0, 1.0) * 14
    score += min(quality / 85.0, 1.0) * 14
    score += min((r5*2 + r15) / 0.6, 1.0) * 8
    score -= min(chase / 50.0, 1.0) * 10
    return max(0.0, min(100.0, round(score,2)))

def classify(score):
    if score >= 85: return "A_PLUS"
    if score >= 75: return "STRONG"
    if score >= 65: return "DEVELOPING"
    if score >= 55: return "WATCH"
    return "WEAK"

def direction_ok(r):
    direction = str(r.get("direction","")).upper()
    vwap = _first_num(r, ALIASES["vwap_dist"], 0.0) or 0.0
    fop = _first_num(r, ALIASES["from_open_pct"], 0.0) or 0.0
    if direction == "BULLISH":
        return vwap >= 0 and fop >= 0
    if direction == "BEARISH":
        return vwap <= 0 and fop <= 0
    return True

def main():
    ap = argparse.ArgumentParser(description="READ-ONLY APlus chart-engine forensic replay")
    ap.add_argument("--day", default="2026-08-20")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--output", default="data/chart_engine_research")
    args = ap.parse_args()

    symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    files = discover_files(args.day)
    if not files:
        raise SystemExit(f"No timestamped scanner JSON snapshots found for {args.day}")

    outdir = ROOT / args.output / args.day
    outdir.mkdir(parents=True, exist_ok=True)

    per_symbol = defaultdict(list)
    parsed_files = 0

    for p in files:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        parsed_files += 1
        file_ts = infer_timestamp(p, obj if isinstance(obj,dict) else {})
        seen = set()
        for row in walk_rows(obj):
            sym = str(row.get("symbol","")).upper().strip()
            if sym not in symbols:
                continue
            # Avoid duplicate same-symbol dicts within same snapshot.
            sig = (sym, str(row.get("stage","")), str(row.get("selection_tier","")), str(row.get("score","")))
            if sig in seen:
                continue
            seen.add(sig)

            r = dict(row)
            r["_file"] = p.name
            r["_snapshot_time"] = file_ts
            r["_chart_score"] = chart_score(r)
            r["_chart_state"] = classify(r["_chart_score"])
            r["_direction_consistent"] = direction_ok(r)
            per_symbol[sym].append(r)

    if not any(per_symbol.values()):
        raise SystemExit("Snapshots found, but none contained requested symbols in candidate-style rows.")

    timeline_rows = []
    summary_rows = []

    for sym in symbols:
        rows = per_symbol.get(sym, [])
        rows.sort(key=lambda r: (r.get("_snapshot_time",""), r.get("_file","")))

        first_seen = rows[0].get("_snapshot_time","") if rows else ""
        first_dev = next((r for r in rows if r["_chart_score"] >= 65 and r["_direction_consistent"]), None)
        first_strong = next((r for r in rows if r["_chart_score"] >= 75 and r["_direction_consistent"]), None)
        first_aplus = next((r for r in rows if r["_chart_score"] >= 85 and r["_direction_consistent"]), None)
        maxr = max(rows, key=lambda r: r["_chart_score"]) if rows else None

        summary_rows.append({
            "symbol": sym,
            "snapshots": len(rows),
            "first_seen": first_seen,
            "first_developing": first_dev.get("_snapshot_time","") if first_dev else "",
            "first_strong": first_strong.get("_snapshot_time","") if first_strong else "",
            "first_a_plus": first_aplus.get("_snapshot_time","") if first_aplus else "",
            "max_chart_score": maxr["_chart_score"] if maxr else "",
            "max_stage": maxr.get("stage","") if maxr else "",
            "max_selection_tier": maxr.get("selection_tier","") if maxr else "",
            "max_direction": maxr.get("direction","") if maxr else "",
            "max_from_open_pct": _first_num(maxr or {}, ALIASES["from_open_pct"], ""),
            "max_relative_volume": _first_num(maxr or {}, ALIASES["rv"], ""),
            "max_trend_alignment": _first_num(maxr or {}, ALIASES["trend"], ""),
            "max_clean_trend": _first_num(maxr or {}, ALIASES["clean"], ""),
            "max_capture": _first_num(maxr or {}, ALIASES["capture"], ""),
            "max_chase": _first_num(maxr or {}, ALIASES["chase"], ""),
        })

        # Keep one timeline row per snapshot/candidate state.
        for r in rows:
            timeline_rows.append({
                "symbol": sym,
                "snapshot_time": r.get("_snapshot_time",""),
                "file": r.get("_file",""),
                "direction": r.get("direction",""),
                "stage": r.get("stage",""),
                "selection_tier": r.get("selection_tier",""),
                "setup_family": r.get("setup_family",""),
                "chart_score": r.get("_chart_score",""),
                "chart_state": r.get("_chart_state",""),
                "direction_consistent": r.get("_direction_consistent",""),
                "quality": _first_num(r, ALIASES["quality"], ""),
                "capture": _first_num(r, ALIASES["capture"], ""),
                "trend_alignment": _first_num(r, ALIASES["trend"], ""),
                "clean_trend": _first_num(r, ALIASES["clean"], ""),
                "chase_risk": _first_num(r, ALIASES["chase"], ""),
                "relative_volume": _first_num(r, ALIASES["rv"], ""),
                "vwap_distance_pct": _first_num(r, ALIASES["vwap_dist"], ""),
                "recent_5m_pct": _first_num(r, ALIASES["recent_5m"], ""),
                "recent_15m_pct": _first_num(r, ALIASES["recent_15m"], ""),
                "from_open_pct": _first_num(r, ALIASES["from_open_pct"], ""),
            })

    with (outdir/"chart_engine_timeline.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f, fieldnames=list(timeline_rows[0].keys()))
        w.writeheader(); w.writerows(timeline_rows)

    with (outdir/"chart_engine_summary.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader(); w.writerows(summary_rows)

    manifest = {
        "mode":"READ_ONLY_FORENSIC_REPLAY",
        "day":args.day,
        "symbols":symbols,
        "snapshot_files_discovered":len(files),
        "snapshot_files_parsed":parsed_files,
        "timeline_rows":len(timeline_rows),
        "note":"Uses persisted scanner state snapshots only. It does not reconstruct exact OHLC candle shapes unless those fields were persisted."
    }
    (outdir/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    print("="*100)
    print("APLUS CHART ENGINE FORENSIC REPLAY - READ ONLY")
    print("="*100)
    print("Day:", args.day)
    print("Snapshot files:", len(files), "parsed:", parsed_files)
    print("Output:", outdir)
    print("")
    print(f"{'SYMBOL':<12} {'SNAPS':>6} {'FIRST DEV':<25} {'FIRST STRONG':<25} {'FIRST A+':<25} {'MAX':>7}")
    for r in summary_rows:
        print(f"{r['symbol']:<12} {r['snapshots']:>6} {str(r['first_developing']):<25.25} {str(r['first_strong']):<25.25} {str(r['first_a_plus']):<25.25} {str(r['max_chart_score']):>7}")
    print("")
    print("Files created:")
    print("  chart_engine_timeline.csv")
    print("  chart_engine_summary.csv")
    print("  run_manifest.json")
    print("")
    print("IMPORTANT: This is research only. No production strategy files were changed.")
    print("="*100)

if __name__ == "__main__":
    main()
