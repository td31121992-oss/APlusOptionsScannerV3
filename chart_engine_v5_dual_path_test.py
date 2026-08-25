from __future__ import annotations
import argparse, csv, json
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def num(v, default=None):
    try:
        if v in ("", None): return default
        return float(v)
    except Exception:
        return default

def dt(v):
    try: return datetime.fromisoformat(str(v))
    except Exception: return None

def read_csv(p):
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_csv(p, rows):
    if not rows:
        p.write_text("", encoding="utf-8")
        return
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

def canonical_per_minute(rows):
    best={}
    for r in rows:
        t=dt(r.get("snapshot_time"))
        sym=str(r.get("symbol","")).upper().strip()
        if not t or not sym: continue
        m=t.replace(second=0,microsecond=0)
        richness=sum(1 for v in r.values() if v not in ("",None))
        score=num(r.get("chart_score"),0) or 0
        key=(sym,m)
        rank=(richness,score,t)
        if key not in best or rank>best[key][0]:
            rr=dict(r); rr["_minute"]=m; rr["_ts"]=t
            best[key]=(rank,rr)
    by=defaultdict(list)
    for (_, _),(_,r) in best.items(): by[r["symbol"]].append(r)
    for arr in by.values(): arr.sort(key=lambda x:x["_minute"])
    return by

def sign(r):
    return -1.0 if str(r.get("direction","")).upper()=="BEARISH" else 1.0

def aligned(r):
    d=str(r.get("direction","")).upper()
    v=num(r.get("vwap_distance_pct"),0) or 0
    f=num(r.get("from_open_pct"),0) or 0
    if d=="BULLISH": return v>=0 and f>=0
    if d=="BEARISH": return v<=0 and f<=0
    return True

def fast_breakout(arr, i):
    """Early path: strong/A+ state with acceleration and no excessive chase."""
    r=arr[i]
    score=num(r.get("chart_score"),0) or 0
    q=num(r.get("quality"),0) or 0
    rv=num(r.get("relative_volume"),0) or 0
    trend=num(r.get("trend_alignment"),0) or 0
    clean=num(r.get("clean_trend"),0) or 0
    chase=num(r.get("chase_risk"),0) or 0
    r5=abs(num(r.get("recent_5m_pct"),0) or 0)
    r15=abs(num(r.get("recent_15m_pct"),0) or 0)
    fop=abs(num(r.get("from_open_pct"),0) or 0)
    if not aligned(r): return False
    if score < 82: return False
    if q < 75: return False
    if rv < 1.25: return False
    if clean < 60: return False
    if trend < 35: return False
    if chase > 30: return False
    if fop < 0.45: return False

    # Need either current acceleration or a rapid score rise vs recent state.
    accel = (r5 >= 0.12 or r15 >= 0.22)
    score_jump=False
    if i>0:
        prev=num(arr[i-1].get("chart_score"),0) or 0
        score_jump=(score-prev)>=6
    if not (accel or score_jump): return False

    # Guard against single-snapshot glitches: next minute must stay >=75 when available.
    if i+1 < len(arr):
        gap=(arr[i+1]["_minute"]-r["_minute"]).total_seconds()/60
        if gap<=3 and (num(arr[i+1].get("chart_score"),0) or 0)<75:
            return False
    return True

def persistent_trend(arr, i, window=3, min_aplus=2):
    if i+window>len(arr): return False
    w=arr[i:i+window]
    for a,b in zip(w,w[1:]):
        if (b["_minute"]-a["_minute"]).total_seconds()>180: return False
    dirs=[str(x.get("direction","")).upper() for x in w if str(x.get("direction","")).upper() in ("BULLISH","BEARISH")]
    if dirs and len(set(dirs))!=1: return False
    scores=[num(x.get("chart_score"),0) or 0 for x in w]
    if min(scores)<75 or sum(s>=85 for s in scores)<min_aplus: return False
    if not all(aligned(x) for x in w): return False
    if max(num(x.get("chase_risk"),0) or 0 for x in w)>35: return False
    if max(num(x.get("clean_trend"),0) or 0 for x in w)<65: return False
    if max(num(x.get("trend_alignment"),0) or 0 for x in w)<40: return False
    if scores[-1]<scores[0]-5: return False
    return True

def simulate_exit(arr, idx, horizon=120):
    e=arr[idx]; s=sign(e); base=num(e.get("from_open_pct"),0) or 0; et=e["_minute"]
    mfe=0.0; mae=0.0; peak=0.0; mfe_time=et; last_peak=et
    exitrow=e; reason="TIME_HORIZON"
    for r in arr[idx:]:
        elapsed=(r["_minute"]-et).total_seconds()/60
        if elapsed<0: continue
        if elapsed>horizon: break
        f=num(r.get("from_open_pct"))
        if f is None: continue
        move=(f-base)*s
        exitrow=r
        if move>mfe:
            mfe=move; peak=move; mfe_time=r["_minute"]; last_peak=r["_minute"]
        if move<mae: mae=move

        score=num(r.get("chart_score"),0) or 0

        # Hard protection
        if move<=-0.60:
            reason="HARD_ADVERSE_STOP"; break

        # Dynamic profit protection
        if peak>=1.00:
            allowed=max(0.20, peak*0.25)
            if move<=peak-allowed:
                reason="TIGHT_PROFIT_TRAIL"; break
        elif peak>=0.50:
            allowed=max(0.15, peak*0.35)
            if move<=peak-allowed:
                reason="PROFIT_TRAIL"; break
        elif peak>=0.25:
            allowed=max(0.12, peak*0.45)
            if move<=peak-allowed:
                reason="EARLY_PROFIT_PROTECT"; break

        # Structure deterioration only after some favorable excursion.
        if elapsed>=8 and peak>=0.15 and score<62:
            reason="STRUCTURE_DERIORATION"; break

        # No progress / time decay proxy
        if elapsed>=18:
            no_new_peak=(r["_minute"]-last_peak).total_seconds()/60
            if peak<0.20 and no_new_peak>=18:
                reason="STAGNATION"; break

    realized=((num(exitrow.get("from_open_pct"),base) or base)-base)*s
    gross_capture = (realized/mfe*100) if mfe>=0.25 else None
    protected = max(0.0, realized) / mfe * 100 if mfe>=0.25 and mfe>0 else None
    return {
        "exit_time":exitrow["_minute"].isoformat(),
        "mfe_pp":round(mfe,4),
        "mae_pp":round(mae,4),
        "mfe_time":mfe_time.isoformat(),
        "realized_pp":round(realized,4),
        "capture_efficiency_pct":round(gross_capture,2) if gross_capture is not None else "",
        "profit_protected_pct":round(protected,2) if protected is not None else "",
        "exit_reason":reason,
        "had_tradeable_move":mfe>=0.25,
        "realized_positive":realized>0,
    }

def main():
    ap=argparse.ArgumentParser(description="APlus Chart Engine V5 dual-path trade research")
    ap.add_argument("--day",default="2026-08-20")
    ap.add_argument("--input-root",default="data/chart_engine_research_v2")
    ap.add_argument("--output-root",default="data/chart_engine_research_v5")
    args=ap.parse_args()

    src=ROOT/args.input_root/args.day/"full_market_timeline.csv"
    if not src.is_file(): raise SystemExit(f"Missing {src}")
    by=canonical_per_minute(read_csv(src))
    outdir=ROOT/args.output_root/args.day
    outdir.mkdir(parents=True,exist_ok=True)

    episodes=[]; path_counts=Counter()

    for sym,arr in sorted(by.items()):
        candidates=[]
        # FAST path can fire immediately.
        for i in range(len(arr)):
            if fast_breakout(arr,i):
                candidates.append((arr[i]["_minute"],"FAST_BREAKOUT",i))
                break

        # Persistent path entry is the end of persistence window.
        for i in range(len(arr)):
            if persistent_trend(arr,i):
                j=i+2
                candidates.append((arr[j]["_minute"],"PERSISTENT_TREND",j))
                break

        if not candidates: continue
        candidates.sort(key=lambda x:x[0])
        when,path,idx=candidates[0]
        r=arr[idx]
        sim=simulate_exit(arr,idx)
        row={
            "symbol":sym,
            "entry_path":path,
            "entry_time":when.isoformat(),
            "direction":r.get("direction",""),
            "entry_chart_score":num(r.get("chart_score"),0),
            "entry_quality":num(r.get("quality"),0),
            "entry_relative_volume":num(r.get("relative_volume"),0),
            "entry_trend_alignment":num(r.get("trend_alignment"),0),
            "entry_clean_trend":num(r.get("clean_trend"),0),
            "entry_chase_risk":num(r.get("chase_risk"),0),
            "entry_from_open_pct":num(r.get("from_open_pct"),0),
            **sim
        }
        episodes.append(row); path_counts[path]+=1

    write_csv(outdir/"v5_trade_episodes.csv",episodes)
    write_csv(outdir/"v5_fast_breakout.csv",[x for x in episodes if x["entry_path"]=="FAST_BREAKOUT"])
    write_csv(outdir/"v5_persistent_trend.csv",[x for x in episodes if x["entry_path"]=="PERSISTENT_TREND"])

    def stats(rows):
        n=len(rows)
        if not n: return {}
        trade=[x for x in rows if x["had_tradeable_move"]]
        cap=[num(x.get("capture_efficiency_pct")) for x in rows]
        cap=[x for x in cap if x is not None]
        prot=[num(x.get("profit_protected_pct")) for x in rows]
        prot=[x for x in prot if x is not None]
        return {
            "signals":n,
            "tradeable_move_count":len(trade),
            "tradeable_move_pct":round(100*len(trade)/n,2),
            "positive_exit_count":sum(bool(x["realized_positive"]) for x in rows),
            "positive_exit_pct":round(100*sum(bool(x["realized_positive"]) for x in rows)/n,2),
            "avg_mfe_pp":round(sum(float(x["mfe_pp"]) for x in rows)/n,4),
            "avg_mae_pp":round(sum(float(x["mae_pp"]) for x in rows)/n,4),
            "avg_realized_pp":round(sum(float(x["realized_pp"]) for x in rows)/n,4),
            "avg_capture_efficiency_pct_tradeable_only":round(sum(cap)/len(cap),2) if cap else "",
            "avg_profit_protected_pct_tradeable_only":round(sum(prot)/len(prot),2) if prot else "",
        }

    summary_rows=[]
    for label,subset in [
        ("FAST_BREAKOUT",[x for x in episodes if x["entry_path"]=="FAST_BREAKOUT"]),
        ("PERSISTENT_TREND",[x for x in episodes if x["entry_path"]=="PERSISTENT_TREND"]),
        ("COMBINED",episodes),
    ]:
        s=stats(subset)
        if s: summary_rows.append({"path":label,**s})
    write_csv(outdir/"v5_path_comparison.csv",summary_rows)

    keys=[]
    for sym in ("COFORGE","MCX","SBICARD","MOTILALOFS","PREMIERENE","GLENMARK"):
        e=next((x for x in episodes if x["symbol"]==sym),None)
        if e: keys.append(e)
    write_csv(outdir/"v5_key_cases.csv",keys)

    manifest={
        "mode":"READ_ONLY_DUAL_PATH_ENTRY_AND_EXIT_RESEARCH",
        "day":args.day,
        "symbols_analysed":len(by),
        "signals":len(episodes),
        "path_counts":dict(path_counts),
        "fast_breakout_rule":"early score/quality/RVOL/trend/clean/VWAP + acceleration + chase guard",
        "persistent_rule":"3-minute persistence with >=2 A+ observations",
        "capture_metric_fix":"capture efficiency is calculated only where MFE >= 0.25pp",
        "dhan_api_calls":0,
        "production_files_modified":False,
        "important":"This test does not use exact option premium history. It evaluates underlying-state opportunity and exit behavior."
    }
    (outdir/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    print("="*110)
    print("APLUS CHART ENGINE V5 - DUAL-PATH ENTRY + EXIT RESEARCH")
    print("READ ONLY - NO DHAN CALLS - NO PRODUCTION CHANGES")
    print("="*110)
    print("Day               :",args.day)
    print("Symbols analysed  :",len(by))
    print("Total signals     :",len(episodes))
    print("Path counts       :",dict(path_counts))
    print("")
    print("PATH RESULTS")
    for r in summary_rows:
        print(
            f"{r['path']:<18} signals={r['signals']:<4} "
            f"tradeable={r['tradeable_move_pct']:>6.2f}% "
            f"positive_exit={r['positive_exit_pct']:>6.2f}% "
            f"avg_MFE={r['avg_mfe_pp']:>7.4f} "
            f"avg_realized={r['avg_realized_pp']:>7.4f} "
            f"capture={str(r['avg_capture_efficiency_pct_tradeable_only']):>7}%"
        )
    print("")
    print("KEY CASES")
    for e in keys:
        print(
            f"{e['symbol']:<12} {e['entry_path']:<17} entry={e['entry_time'][11:16]} "
            f"exit={e['exit_time'][11:16]} MFE={float(e['mfe_pp']):>6.3f} "
            f"realized={float(e['realized_pp']):>6.3f} "
            f"capture={str(e['capture_efficiency_pct']):>6}% "
            f"reason={e['exit_reason']}"
        )
    print("")
    print("Files:")
    print("  v5_trade_episodes.csv")
    print("  v5_fast_breakout.csv")
    print("  v5_persistent_trend.csv")
    print("  v5_path_comparison.csv")
    print("  v5_key_cases.csv")
    print("  run_manifest.json")
    print("="*110)

if __name__=="__main__":
    main()
