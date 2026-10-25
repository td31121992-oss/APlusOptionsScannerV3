"""Shadow-only reason-combination study; never changes scanner or trade ledger."""
import argparse, csv, json, math, statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parent / "data" / "three_minute_shadow_replay_20261026_001138" / "shadow_candidates_outcomes.csv"
FEATURES = {
    "trend_weak": "Short-term trend alignment weak",
    "close_weak": "Weak candle close location",
    "vwap_conflict": "VWAP conflicts with direction",
    "body_weak": "Directional candle body weak or opposing",
    "vwap_extension": "VWAP extension",
}

def truth(v):
    return str(v or "").strip().lower() in {"1","true","yes","y"}

def number(v):
    try:
        n=float(str(v).strip())
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):
        return None

def parse_reasons(value):
    s=str(value or "").strip()
    if not s: return []
    try:
        obj=json.loads(s)
        if isinstance(obj,list): return [str(x).strip() for x in obj if str(x).strip()]
        if isinstance(obj,str): s=obj
    except (ValueError,TypeError): pass
    # Reasons may be stored as a delimited string; don't split commas inside arbitrary prose.
    if "||" in s: return [x.strip() for x in s.split("||") if x.strip()]
    if ";" in s: return [x.strip() for x in s.split(";") if x.strip()]
    return [s.strip("[]\"'")]

def metric(rows):
    vals=[r["ret"] for r in rows]
    if not vals: return {"signals":0,"positive_pct":None,"mean_return_pct":None,"median_return_pct":None}
    return {"signals":len(vals),"positive_pct":round(100*sum(x>0 for x in vals)/len(vals),2),
            "mean_return_pct":round(statistics.fmean(vals),6),"median_return_pct":round(statistics.median(vals),6)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,default=DEFAULT_INPUT)
    p.add_argument("--output-dir",type=Path,default=None)
    p.add_argument("--start",default="2026-10-14")
    p.add_argument("--end-exclusive",default="2026-10-23")
    p.add_argument("--spacing-minutes",type=int,default=15)
    a=p.parse_args()
    if not a.input.is_file(): p.error("input not found: "+str(a.input))
    start,end=date.fromisoformat(a.start),date.fromisoformat(a.end_exclusive)
    with a.input.open(newline="",encoding="utf-8-sig") as f:
        rd=csv.DictReader(f); cols=rd.fieldnames or []; raw=list(rd)
    needed={"symbol","date","timestamp","direction","verdict","close_return_percent","horizon_complete","reasons"}
    if needed-set(cols): p.error("missing columns: "+", ".join(sorted(needed-set(cols))))
    parsed=[]; malformed=0; incomplete=0
    for x in raw:
        try:
            ts=datetime.fromisoformat(str(x["timestamp"]).strip().replace("Z","+00:00"))
            day=date.fromisoformat(str(x["date"]).strip()[:10]); sym=str(x["symbol"]).strip().upper()
            if not sym: raise ValueError()
        except (ValueError,TypeError,KeyError):
            malformed+=1; continue
        done=truth(x.get("horizon_complete")); ret=number(x.get("close_return_percent"))
        if not done: incomplete+=1; continue
        if ret is None: malformed+=1; continue
        reasons=parse_reasons(x.get("reasons"))
        joined=" | ".join(reasons)
        flags={k:(v.lower() in joined.lower()) for k,v in FEATURES.items()}
        # Exact phrase matching for the observed labels; VWAP extension is prefix matching.
        parsed.append({"symbol":sym,"day":day,"ts":ts,"direction":str(x["direction"]).strip().upper(),
                       "verdict":str(x["verdict"]).strip().upper(),"ret":ret,"reasons":reasons,**flags})
    lanes=defaultdict(list)
    for r in parsed: lanes[(r["symbol"],r["day"])].append(r)
    spaced=[]
    for lane in lanes.values():
        last=None
        for r in sorted(lane,key=lambda z:z["ts"]):
            if last is None or r["ts"]>=last+timedelta(minutes=a.spacing_minutes):
                spaced.append(r); last=r["ts"]
    test=[r for r in spaced if start<=r["day"]<end and r["direction"]=="BULLISH"]
    if not test: p.error("no bullish holdout rows found")
    # Test each feature individually, pairs, and selected three-feature combination.
    specs=[
      ("Existing WATCH_WEAK_BREAK verdict",lambda r:r["verdict"]=="WATCH_WEAK_BREAK"),
      ("Weak trend only",lambda r:r["trend_weak"]),
      ("Weak close only",lambda r:r["close_weak"]),
      ("VWAP conflict only",lambda r:r["vwap_conflict"]),
      ("Weak trend AND weak close",lambda r:r["trend_weak"] and r["close_weak"]),
      ("Weak trend AND VWAP conflict",lambda r:r["trend_weak"] and r["vwap_conflict"]),
      ("Weak close AND VWAP conflict",lambda r:r["close_weak"] and r["vwap_conflict"]),
      ("Weak trend AND weak close AND VWAP conflict",lambda r:r["trend_weak"] and r["close_weak"] and r["vwap_conflict"]),
      ("Weak trend AND weak close AND weak body",lambda r:r["trend_weak"] and r["close_weak"] and r["body_weak"]),
    ]
    results=[]; daily=[]
    for name,fn in specs:
        excluded=[r for r in test if fn(r)]
        kept=[r for r in test if not fn(r)]
        ex=metric(excluded); km=metric(kept); base=metric(test)
        day_changes=[]
        for d in sorted({r["day"] for r in test}):
            b=[r for r in test if r["day"]==d]; k=[r for r in b if not fn(r)]
            bm,kk=metric(b),metric(k)
            change=None if kk["mean_return_pct"] is None else round(kk["mean_return_pct"]-bm["mean_return_pct"],6)
            day_changes.append(change)
            daily.append({"scenario":name,"date":d.isoformat(),"baseline_signals":len(b),"excluded_signals":sum(fn(r) for r in b),
                          "remaining_signals":len(k),"baseline_mean_pct":bm["mean_return_pct"],"remaining_mean_pct":kk["mean_return_pct"],
                          "mean_change_pp":change})
        results.append({"scenario":name,"baseline_signals":len(test),"excluded_signals":len(excluded),
                        "excluded_pct":round(100*len(excluded)/len(test),2),"excluded_positive_pct":ex["positive_pct"],
                        "excluded_mean_return_pct":ex["mean_return_pct"],"excluded_median_return_pct":ex["median_return_pct"],
                        "remaining_signals":len(kept),"remaining_positive_pct":km["positive_pct"],
                        "remaining_mean_return_pct":km["mean_return_pct"],"remaining_median_return_pct":km["median_return_pct"],
                        "mean_change_vs_baseline_pp":None if km["mean_return_pct"] is None else round(km["mean_return_pct"]-base["mean_return_pct"],6),
                        "dates_improved":sum(x is not None and x>0 for x in day_changes),
                        "dates_worsened":sum(x is not None and x<0 for x in day_changes),
                        "excluded_existing_gate_winners":sum(r["verdict"]!="WATCH_WEAK_BREAK" and r["ret"]>0 for r in excluded),
                        "note":"Underlying-stock returns; overlapping reason flags; exploratory only."})
    out=a.output_dir or a.input.parent; out.mkdir(parents=True,exist_ok=True)
    for filename,data in [("shadow_weak_break_reason_combinations.csv",results),("shadow_weak_break_reason_combinations_daily.csv",daily)]:
        path=out/filename
        with path.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for row in data for k in row)))
            w.writeheader(); w.writerows(data)
    meta={"input":str(a.input.resolve()),"raw_rows":len(raw),"complete_parsed_rows":len(parsed),"incomplete_horizon_rows":incomplete,
          "malformed_rows":malformed,"spaced_rows":len(spaced),"bullish_holdout_rows":len(test),
          "holdout_start_inclusive":start.isoformat(),"holdout_end_exclusive":end.isoformat(),"spacing_minutes":a.spacing_minutes,
          "feature_phrases":FEATURES,"note":"No production changes. Reasons can overlap; stock returns are not option P&L."}
    (out/"shadow_weak_break_reason_combinations_metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    print("=== SHADOW REASON COMBINATION RESULTS ===")
    for r in results: print(r)
    print("=== DAILY RESULTS ===")
    for r in daily: print(r)
    print("Saved reports:",out)
    print("SHADOW ONLY: no production scanner or paper-trade ledger changes.")
    return 0
if __name__=="__main__": raise SystemExit(main())
