"""Read-only v2 audit for WATCH_WEAK_BREAK shadow replay. No production or ledger writes."""
import argparse, csv, json, math, statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parent / "data" / "three_minute_shadow_replay_20261026_001138" / "shadow_candidates_outcomes.csv"

def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None

def boolean(v):
    return str(v or "").strip().lower() in {"1", "true", "yes", "y"}

def stats(rows):
    vals = [r["ret"] for r in rows if r["ret"] is not None]
    if not vals:
        return {"signals": 0, "positive_pct": None, "mean_pct": None, "median_pct": None}
    return {"signals": len(vals), "positive_pct": round(100*sum(x>0 for x in vals)/len(vals),2),
            "mean_pct": round(statistics.fmean(vals),6), "median_pct": round(statistics.median(vals),6)}

def write(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def tokens(v):
    s = str(v or "").strip()
    if not s: return ["(blank reason)"]
    try:
        j = json.loads(s)
        if isinstance(j, list): return [str(x).strip() for x in j if str(x).strip()] or ["(blank reason)"]
        if isinstance(j, str): s = j
    except (ValueError, TypeError): pass
    for sep in (";", "|", ","):
        if sep in s: return [x.strip().strip("[]\"'") for x in s.split(sep) if x.strip().strip("[]\"'")]
    return [s.strip().strip("[]\"'")]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,default=DEFAULT_INPUT)
    p.add_argument("--output-dir",type=Path,default=None)
    p.add_argument("--start",default="2026-10-14")
    p.add_argument("--end-exclusive",default="2026-10-23")
    p.add_argument("--spacing-minutes",type=int,default=15)
    a=p.parse_args()
    if a.spacing_minutes<1: p.error("--spacing-minutes must be positive")
    start,end=date.fromisoformat(a.start),date.fromisoformat(a.end_exclusive)
    if end<=start: p.error("--end-exclusive must be after --start")
    if not a.input.is_file(): p.error("input not found: "+str(a.input))
    with a.input.open(newline="",encoding="utf-8-sig") as f:
        rd=csv.DictReader(f); cols=rd.fieldnames or []; raw=list(rd)
    need={"symbol","date","timestamp","direction","verdict","close_return_percent","horizon_complete"}
    if need-set(cols): p.error("missing columns: "+", ".join(sorted(need-set(cols))))
    rows=[]; malformed=0; incomplete=0; complete=0
    for x in raw:
        try:
            ts=datetime.fromisoformat(str(x["timestamp"]).strip().replace("Z","+00:00"))
            day=date.fromisoformat(str(x["date"]).strip()[:10]); sym=str(x["symbol"]).strip().upper()
            if not sym: raise ValueError()
        except (ValueError,TypeError,KeyError):
            malformed+=1; continue
        done=boolean(x.get("horizon_complete")); ret=num(x.get("close_return_percent"))
        if not done: incomplete+=1
        elif ret is None: malformed+=1; continue
        else: complete+=1
        rows.append({"symbol":sym,"day":day,"ts":ts,"direction":str(x.get("direction","")).strip().upper(),
                     "verdict":str(x.get("verdict","")).strip().upper(),"ret":ret if done else None,
                     "complete":done and ret is not None,"raw":x,
                     "shadow_only":boolean(x.get("shadow_only")),"authorized":boolean(x.get("trade_authorized"))})
    lanes=defaultdict(list)
    for r in rows: lanes[(r["symbol"],r["day"])].append(r)
    spaced=[]
    for lane in lanes.values():
        last=None
        for r in sorted(lane,key=lambda z:z["ts"]):
            if last is None or r["ts"]>=last+timedelta(minutes=a.spacing_minutes):
                spaced.append(r); last=r["ts"]
    test=[r for r in spaced if start<=r["day"]<end and r["direction"]=="BULLISH" and r["complete"]]
    if not test: p.error("no complete bullish holdout observations found")
    kept=[r for r in test if r["verdict"]!="WATCH_WEAK_BREAK"]
    rejected=[r for r in test if r["verdict"]=="WATCH_WEAK_BREAK"]
    bm=stats(test); gm=stats(kept); xm=stats(rejected)
    summary=[]
    for label, subset in (("Baseline",test),("Gate scenario",kept),("Rejected WATCH_WEAK_BREAK",rejected)):
        m=stats(subset); meanchange=None if m["mean_pct"] is None or bm["mean_pct"] is None else round(m["mean_pct"]-bm["mean_pct"],6)
        summary.append({"scenario":label,**m,"dates":len({r["day"] for r in subset}),"mean_change_vs_baseline_pp":meanchange})
    daily=[]
    for d in sorted({r["day"] for r in test}):
        b=[r for r in test if r["day"]==d]; g=[r for r in b if r["verdict"]!="WATCH_WEAK_BREAK"]
        mb,mg=stats(b),stats(g)
        daily.append({"date":d.isoformat(),"baseline_signals":len(b),"rejected_signals":sum(r["verdict"]=="WATCH_WEAK_BREAK" for r in b),
                      "baseline_mean_pct":mb["mean_pct"],"gate_mean_pct":mg["mean_pct"],
                      "mean_change_pp":None if mg["mean_pct"] is None else round(mg["mean_pct"]-mb["mean_pct"],6),
                      "baseline_positive_pct":mb["positive_pct"],"gate_positive_pct":mg["positive_pct"]})
    symbols=[]
    for sym in sorted({r["symbol"] for r in test}):
        b=[r for r in test if r["symbol"]==sym]; x=[r for r in b if r["verdict"]=="WATCH_WEAK_BREAK"]
        if not x: continue
        g=[r for r in b if r["verdict"]!="WATCH_WEAK_BREAK"]; mb,mg,mx=stats(b),stats(g),stats(x)
        symbols.append({"symbol":sym,"baseline_signals":len(b),"rejected_signals":len(x),"rejected_positive_pct":mx["positive_pct"],
                        "rejected_mean_pct":mx["mean_pct"],"baseline_mean_pct":mb["mean_pct"],"gate_mean_pct":mg["mean_pct"],
                        "mean_change_pp":None if mg["mean_pct"] is None else round(mg["mean_pct"]-mb["mean_pct"],6)})
    reason_col=next((c for c in ("reasons","reason","quality_gate_reasons","verdict_reasons") if c in cols),None)
    reason_map=defaultdict(list)
    if reason_col:
        for r in test:
            group="REJECTED_WATCH_WEAK_BREAK" if r["verdict"]=="WATCH_WEAK_BREAK" else "KEPT_BY_GATE"
            for token in tokens(r["raw"].get(reason_col)):
                reason_map[(group,token)].append(r)
    reasons=[]
    for (group,reason),subset in sorted(reason_map.items()):
        m=stats(subset); reasons.append({"group":group,"reason":reason,**m,"symbols":len({r["symbol"] for r in subset}),"dates":len({r["day"] for r in subset})})
    score_cols=[c for c in cols if c.lower().endswith("_score") or c in {"selection_score","movement_capture_score","trend_alignment_score","clean_trend_score","chase_risk_score"}]
    scores=[]
    for field in score_cols:
        valid=[(r,num(r["raw"].get(field))) for r in test if num(r["raw"].get(field)) is not None]
        if len(valid)<4: continue
        vals=sorted(v for _,v in valid); q1=vals[len(vals)//3]; q2=vals[(2*len(vals))//3]
        for group,subset in (("REJECTED_WATCH_WEAK_BREAK",[r for r,v in valid if r["verdict"]=="WATCH_WEAK_BREAK"]),
                             ("KEPT_BY_GATE",[r for r,v in valid if r["verdict"]!="WATCH_WEAK_BREAK"])):
            for band,fn in (("LOW",lambda v:v<=q1),("MID",lambda v:q1<v<=q2),("HIGH",lambda v:v>q2)):
                br=[r for r in subset if (v:=num(r["raw"].get(field))) is not None and fn(v)]
                if br:
                    m=stats(br); bandvals=[num(r["raw"].get(field)) for r in br]
                    scores.append({"score_field":field,"group":group,"band":band,"band_min":min(bandvals),"band_max":max(bandvals),**m})
    out=a.output_dir or a.input.parent; out.mkdir(parents=True,exist_ok=True)
    write(out/"shadow_weak_break_audit_v2_summary.csv",summary)
    write(out/"shadow_weak_break_audit_v2_daily.csv",daily)
    write(out/"shadow_weak_break_audit_v2_symbols.csv",symbols)
    write(out/"shadow_weak_break_audit_v2_reasons.csv",reasons)
    write(out/"shadow_weak_break_audit_v2_scores.csv",scores)
    meta={"input":str(a.input.resolve()),"raw_rows":len(raw),"structurally_parsed_rows":len(rows),
          "complete_outcome_rows":complete,"incomplete_horizon_rows":incomplete,"malformed_rows":malformed,
          "spaced_rows":len(spaced),"holdout_start_inclusive":start.isoformat(),"holdout_end_exclusive":end.isoformat(),
          "spacing_minutes":a.spacing_minutes,"complete_bullish_holdout_rows":len(test),
          "shadow_only_false_rows":sum(not r["shadow_only"] for r in test),
          "trade_authorized_true_rows":sum(r["authorized"] for r in test),
          "dates_improved":sum((r["mean_change_pp"] or 0)>0 for r in daily),
          "dates_worsened":sum((r["mean_change_pp"] or 0)<0 for r in daily),
          "reason_column_used":reason_col,"score_columns_found":score_cols,
          "note":"Underlying-stock returns only, not option P&L. Reason/score groupings are descriptive, not causal proof."}
    (out/"shadow_weak_break_audit_v2_metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    print("\n=== CORRECTED DATA QUALITY ===\n"+json.dumps(meta,indent=2))
    print("\n=== OVERALL SUMMARY ===")
    for r in summary: print(r)
    print("\n=== DAILY CONSISTENCY ===")
    for r in daily: print(r)
    print("\n=== REJECTION REASONS (first 40) ===")
    for r in reasons[:40]: print(r)
    print("\n=== SCORE BANDS (first 40) ===")
    for r in scores[:40]: print(r)
    print("\nReports saved to:",out)
    print("SHADOW ONLY: no production or paper-trade ledger changes.")
    return 0

if __name__=="__main__": raise SystemExit(main())
