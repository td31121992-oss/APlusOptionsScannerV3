from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict, Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"

STATE_RANK = {"WEAK":0, "WATCH":1, "DEVELOPING":2, "STRONG":3, "A_PLUS":4}

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

def discover_files(day: str):
    key = day.replace("-","")
    arr=[]
    for p in REPORTS.glob("*.json"):
        if p.name.startswith(f"intraday_movement_{key}_") or p.name.startswith(f"opening_momentum_{key}_"):
            arr.append(p)
    return sorted(arr, key=lambda p:p.name)

def walk_rows(obj: Any):
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

def infer_timestamp(path: Path, obj):
    if isinstance(obj, dict):
        for k in ("generated_at","timestamp","as_of","created_at"):
            v=obj.get(k)
            if isinstance(v,str) and v:
                return v
    m=re.search(r"_(\d{8})_(\d{6})\.json$", path.name)
    if m:
        d,t=m.groups()
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}+05:30"
    return ""

def chart_score(r):
    f=abs(_first_num(r,ALIASES["from_open_pct"],0) or 0)
    rv=_first_num(r,ALIASES["rv"],0) or 0
    vw=abs(_first_num(r,ALIASES["vwap_dist"],0) or 0)
    tr=_first_num(r,ALIASES["trend"],0) or 0
    cl=_first_num(r,ALIASES["clean"],0) or 0
    cp=_first_num(r,ALIASES["capture"],0) or 0
    q=_first_num(r,ALIASES["quality"],0) or 0
    ch=_first_num(r,ALIASES["chase"],0) or 0
    r5=abs(_first_num(r,ALIASES["recent_5m"],0) or 0)
    r15=abs(_first_num(r,ALIASES["recent_15m"],0) or 0)
    s=0
    s += min(f/2.5,1)*12
    s += min(rv/2.0,1)*12
    s += min(vw/1.0,1)*8
    s += min(tr/80,1)*16
    s += min(cl/80,1)*16
    s += min(cp/75,1)*14
    s += min(q/85,1)*14
    s += min((r5*2+r15)/0.6,1)*8
    s -= min(ch/50,1)*10
    return round(max(0,min(100,s)),2)

def classify(s):
    if s>=85:return "A_PLUS"
    if s>=75:return "STRONG"
    if s>=65:return "DEVELOPING"
    if s>=55:return "WATCH"
    return "WEAK"

def direction_consistent(r):
    d=str(r.get("direction","")).upper()
    v=_first_num(r,ALIASES["vwap_dist"],0) or 0
    f=_first_num(r,ALIASES["from_open_pct"],0) or 0
    if d=="BULLISH": return v>=0 and f>=0
    if d=="BEARISH": return v<=0 and f<=0
    return True

def richness(r):
    # Canonical record priority: more persisted fields, then production score, then chart score.
    nonempty=sum(1 for v in r.values() if v not in ("",None,[],{}))
    q=_first_num(r,ALIASES["quality"],0) or 0
    c=chart_score(r)
    stage_bonus=2 if r.get("stage") else 0
    tier_bonus=1 if r.get("selection_tier") else 0
    return (nonempty, q, c, stage_bonus+tier_bonus)

def load_market_watch():
    p=REPORTS/"fno_market_watch_latest.json"
    if not p.is_file(): return {}
    try:
        obj=json.loads(p.read_text(encoding="utf-8"))
        return {str(r.get("symbol","")).upper():r for r in obj.get("rows",[]) if isinstance(r,dict)}
    except Exception:
        return {}

def main():
    ap=argparse.ArgumentParser(description="APlus Chart Engine V2 - canonical full-market forensic replay")
    ap.add_argument("--day",default="2026-08-20")
    ap.add_argument("--output",default="data/chart_engine_research_v2")
    ap.add_argument("--winner-threshold",type=float,default=2.0,
                    help="absolute end-of-day from-open move used only for cohort comparison")
    args=ap.parse_args()

    files=discover_files(args.day)
    if not files:
        raise SystemExit("No timestamped scanner snapshots found.")

    # Keyed by (symbol, snapshot timestamp) so exactly one canonical state survives per scanner time.
    canon={}
    raw_count=0
    parsed=0
    for p in files:
        try:
            obj=json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        parsed += 1
        ts=infer_timestamp(p,obj)
        for r in walk_rows(obj):
            sym=str(r.get("symbol","")).upper().strip()
            if not sym or not ts:
                continue
            raw_count += 1
            rr=dict(r)
            rr["_file"]=p.name
            rr["_snapshot_time"]=ts
            rr["_chart_score"]=chart_score(rr)
            rr["_chart_state"]=classify(rr["_chart_score"])
            rr["_direction_consistent"]=direction_consistent(rr)
            key=(sym,ts)
            old=canon.get(key)
            if old is None or richness(rr)>richness(old):
                canon[key]=rr

    bysym=defaultdict(list)
    for (sym,ts),r in canon.items():
        bysym[sym].append(r)
    for arr in bysym.values():
        arr.sort(key=lambda r:r["_snapshot_time"])

    mw=load_market_watch()
    outdir=ROOT/args.output/args.day
    outdir.mkdir(parents=True,exist_ok=True)

    timeline=[]
    transitions=[]
    summaries=[]

    for sym,rows in sorted(bysym.items()):
        prev=None
        highest=0
        first_by_state={}
        state_counts=Counter()
        deteriorations=0
        recoveries=0

        for r in rows:
            state=r["_chart_state"] if r["_direction_consistent"] else "WEAK"
            score=r["_chart_score"]
            rank=STATE_RANK[state]
            state_counts[state]+=1
            first_by_state.setdefault(state,r["_snapshot_time"])

            if prev is not None:
                pr=STATE_RANK[prev]
                if rank < pr:
                    deteriorations += 1
                    transitions.append({
                        "symbol":sym,"timestamp":r["_snapshot_time"],
                        "from_state":prev,"to_state":state,
                        "transition":"DETERIORATION",
                        "chart_score":score,"stage":r.get("stage",""),
                        "selection_tier":r.get("selection_tier",""),
                    })
                elif rank > pr:
                    recoveries += 1
                    transitions.append({
                        "symbol":sym,"timestamp":r["_snapshot_time"],
                        "from_state":prev,"to_state":state,
                        "transition":"IMPROVEMENT",
                        "chart_score":score,"stage":r.get("stage",""),
                        "selection_tier":r.get("selection_tier",""),
                    })
            prev=state
            highest=max(highest,rank)

            timeline.append({
                "symbol":sym,
                "snapshot_time":r["_snapshot_time"],
                "file":r["_file"],
                "direction":r.get("direction",""),
                "stage":r.get("stage",""),
                "selection_tier":r.get("selection_tier",""),
                "setup_family":r.get("setup_family",""),
                "chart_score":score,
                "chart_state":state,
                "direction_consistent":r["_direction_consistent"],
                "quality":_first_num(r,ALIASES["quality"],""),
                "capture":_first_num(r,ALIASES["capture"],""),
                "trend_alignment":_first_num(r,ALIASES["trend"],""),
                "clean_trend":_first_num(r,ALIASES["clean"],""),
                "chase_risk":_first_num(r,ALIASES["chase"],""),
                "relative_volume":_first_num(r,ALIASES["rv"],""),
                "vwap_distance_pct":_first_num(r,ALIASES["vwap_dist"],""),
                "recent_5m_pct":_first_num(r,ALIASES["recent_5m"],""),
                "recent_15m_pct":_first_num(r,ALIASES["recent_15m"],""),
                "from_open_pct":_first_num(r,ALIASES["from_open_pct"],""),
            })

        maxr=max(rows,key=lambda x:x["_chart_score"])
        final=mw.get(sym,{})
        eod=_num(final.get("from_open_pct"))
        final_abs=abs(eod) if eod is not None else None
        cohort = (
            "BIG_MOVER" if final_abs is not None and final_abs>=args.winner_threshold
            else "CONTROL" if final_abs is not None
            else "NO_EOD_DATA"
        )

        summaries.append({
            "symbol":sym,
            "canonical_snapshots":len(rows),
            "first_seen":rows[0]["_snapshot_time"],
            "first_watch":first_by_state.get("WATCH",""),
            "first_developing":first_by_state.get("DEVELOPING",""),
            "first_strong":first_by_state.get("STRONG",""),
            "first_a_plus":first_by_state.get("A_PLUS",""),
            "max_chart_score":maxr["_chart_score"],
            "max_chart_state":classify(maxr["_chart_score"]),
            "max_stage":maxr.get("stage",""),
            "max_selection_tier":maxr.get("selection_tier",""),
            "deteriorations":deteriorations,
            "improvements":recoveries,
            "eod_from_open_pct":eod if eod is not None else "",
            "eod_abs_move_pct":final_abs if final_abs is not None else "",
            "cohort":cohort,
            "count_weak":state_counts["WEAK"],
            "count_watch":state_counts["WATCH"],
            "count_developing":state_counts["DEVELOPING"],
            "count_strong":state_counts["STRONG"],
            "count_a_plus":state_counts["A_PLUS"],
        })

    def write_csv(path,rows):
        if not rows: return
        with path.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)

    write_csv(outdir/"full_market_timeline.csv",timeline)
    write_csv(outdir/"state_transitions.csv",transitions)
    write_csv(outdir/"symbol_summary.csv",summaries)

    # Cohort comparison: do early STRONG/A+ states concentrate among eventual big movers?
    cohort_rows=[]
    for cohort in ("BIG_MOVER","CONTROL"):
        ss=[r for r in summaries if r["cohort"]==cohort]
        if not ss: continue
        n=len(ss)
        early_strong=sum(1 for r in ss if r["first_strong"])
        early_aplus=sum(1 for r in ss if r["first_a_plus"])
        max85=sum(1 for r in ss if _num(r["max_chart_score"],0)>=85)
        cohort_rows.append({
            "cohort":cohort,
            "symbols":n,
            "ever_strong":early_strong,
            "ever_strong_pct":round(100*early_strong/n,2),
            "ever_a_plus":early_aplus,
            "ever_a_plus_pct":round(100*early_aplus/n,2),
            "max_score_85_plus":max85,
            "max_score_85_plus_pct":round(100*max85/n,2),
            "avg_max_chart_score":round(sum(float(r["max_chart_score"]) for r in ss)/n,2),
        })
    write_csv(outdir/"cohort_comparison.csv",cohort_rows)

    # Ranked candidates for quick review.
    ranked=sorted(
        [r for r in summaries if r["cohort"]!="NO_EOD_DATA"],
        key=lambda r:(float(r["max_chart_score"]), abs(float(r["eod_from_open_pct"] or 0))),
        reverse=True,
    )
    write_csv(outdir/"ranked_symbols.csv",ranked)

    manifest={
        "mode":"READ_ONLY_CANONICAL_FULL_MARKET_REPLAY",
        "day":args.day,
        "snapshot_files_discovered":len(files),
        "snapshot_files_parsed":parsed,
        "raw_candidate_rows":raw_count,
        "canonical_symbol_timestamp_rows":len(canon),
        "symbols":len(bysym),
        "winner_threshold_abs_from_open_pct":args.winner_threshold,
        "production_files_modified":False,
        "dhan_api_calls":0,
        "note":"One canonical row per symbol per snapshot timestamp. Cohort comparison uses latest persisted EOD from-open values only."
    }
    (outdir/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    print("="*104)
    print("APLUS CHART ENGINE V2 - CANONICAL FULL-MARKET REPLAY")
    print("READ ONLY - NO DHAN CALLS - NO PRODUCTION CHANGES")
    print("="*104)
    print("Day                         :",args.day)
    print("Snapshot files              :",len(files))
    print("Raw candidate rows          :",raw_count)
    print("Canonical symbol/time rows  :",len(canon))
    print("Symbols analysed            :",len(bysym))
    print("Output                      :",outdir)
    print("")
    print("COHORT COMPARISON")
    for r in cohort_rows:
        print(
            f"{r['cohort']:<10} symbols={r['symbols']:<4} "
            f"ever_STRONG={r['ever_strong_pct']:>6.2f}% "
            f"ever_A+={r['ever_a_plus_pct']:>6.2f}% "
            f"avg_max_score={r['avg_max_chart_score']:>6.2f}"
        )
    print("")
    print("TOP 15 BY MAX CHART SCORE")
    for r in ranked[:15]:
        print(
            f"{r['symbol']:<14} score={float(r['max_chart_score']):>6.2f} "
            f"EOD={float(r['eod_from_open_pct']):>7.3f}% "
            f"cohort={r['cohort']:<9} "
            f"first_strong={str(r['first_strong'])[11:19] if r['first_strong'] else '-':<8} "
            f"first_A+={str(r['first_a_plus'])[11:19] if r['first_a_plus'] else '-':<8}"
        )
    print("")
    print("Files:")
    print("  full_market_timeline.csv")
    print("  state_transitions.csv")
    print("  symbol_summary.csv")
    print("  cohort_comparison.csv")
    print("  ranked_symbols.csv")
    print("  run_manifest.json")
    print("="*104)

if __name__=="__main__":
    main()
