from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def num(v, default=None):
    try:
        if v in ("",None): return default
        return float(v)
    except Exception:
        return default

def ts(s):
    try: return datetime.fromisoformat(str(s))
    except Exception: return None

def read_csv(p):
    with p.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def write_csv(p,rows):
    if not rows:
        p.write_text("",encoding="utf-8"); return
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows)

def sign(direction): return -1.0 if str(direction).upper()=="BEARISH" else 1.0

def per_minute(rows):
    best={}
    for r in rows:
        t=ts(r.get("snapshot_time"))
        if not t: continue
        sym=str(r.get("symbol","")).upper().strip()
        if not sym: continue
        m=t.replace(second=0,microsecond=0)
        richness=sum(1 for v in r.values() if v not in ("",None))
        score=num(r.get("chart_score"),0) or 0
        key=(sym,m)
        rank=(richness,score,t)
        if key not in best or rank>best[key][0]:
            rr=dict(r);rr["_minute"]=m;best[key]=(rank,rr)
    out=defaultdict(list)
    for (_, _),(_,r) in best.items(): out[r["symbol"]].append(r)
    for arr in out.values(): arr.sort(key=lambda x:x["_minute"])
    return out

def confirm(arr,i,window=3,min_aplus=2):
    if i+window>len(arr): return None
    w=arr[i:i+window]
    for a,b in zip(w,w[1:]):
        if (b["_minute"]-a["_minute"]).total_seconds()>180: return None
    dirs=[str(x.get("direction","")).upper() for x in w if str(x.get("direction","")).upper() in ("BULLISH","BEARISH")]
    if dirs and len(set(dirs))!=1: return None
    scores=[num(x.get("chart_score"),0) or 0 for x in w]
    if min(scores)<75 or sum(s>=85 for s in scores)<min_aplus: return None
    chase=[num(x.get("chase_risk"),0) or 0 for x in w]
    clean=[num(x.get("clean_trend"),0) or 0 for x in w]
    trend=[num(x.get("trend_alignment"),0) or 0 for x in w]
    if max(chase)>35 or max(clean)<65 or max(trend)<40: return None
    if scores[-1]<scores[0]-5: return None
    return i+window-1

def episode(arr,idx,horizon=120,hard_stop=0.60,trail_start=0.50,trail_frac=0.35,stagnation=20,min_progress=0.20,break_score=65):
    e=arr[idx]; s=sign(e.get("direction")); base=num(e.get("from_open_pct"),0) or 0; et=e["_minute"]
    mfe=0.0; mae=0.0; peak=0.0; mfe_time=et; last_prog=et; exit_row=e; reason="TIME_HORIZON"; detail=[]
    for r in arr[idx:]:
        elapsed=(r["_minute"]-et).total_seconds()/60
        if elapsed<0: continue
        if elapsed>horizon: break
        f=num(r.get("from_open_pct"))
        if f is None: continue
        move=(f-base)*s
        if move>mfe:
            mfe=move;peak=move;mfe_time=r["_minute"];last_prog=r["_minute"]
        if move<mae: mae=move
        score=num(r.get("chart_score"),0) or 0
        detail.append({"symbol":r["symbol"],"time":r["_minute"].isoformat(),"elapsed_min":elapsed,
                       "direction":r.get("direction",""),"chart_score":score,"from_open_pct":f,
                       "directional_move_pp":round(move,4),"mfe_pp":round(mfe,4),"mae_pp":round(mae,4)})
        exit_row=r
        if move<=-hard_stop:
            reason="HARD_ADVERSE_STOP";break
        if peak>=trail_start:
            allowed=max(0.15,peak*trail_frac)
            if move<=peak-allowed:
                reason="PROFIT_TRAIL_RETRACE";break
        if elapsed>=10 and score<break_score and peak>0:
            reason="STRUCTURE_DERIORATION";break
        if elapsed>=stagnation:
            mins=(r["_minute"]-last_prog).total_seconds()/60
            if mfe<min_progress and mins>=stagnation:
                reason="STAGNATION_NO_PROGRESS";break
    realized=((num(exit_row.get("from_open_pct"),base) or base)-base)*s
    cap=(realized/mfe*100) if mfe>1e-9 else 0.0
    return {"entry_time":et.isoformat(),"exit_time":exit_row["_minute"].isoformat(),"direction":e.get("direction",""),
            "entry_chart_score":num(e.get("chart_score"),0),"entry_from_open_pct":base,"mfe_pp":round(mfe,4),
            "mae_pp":round(mae,4),"mfe_time":mfe_time.isoformat(),"realized_pp":round(realized,4),
            "capture_efficiency_pct":round(cap,2),"exit_reason":reason,"detail":detail}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--day",default="2026-08-20")
    ap.add_argument("--input-root",default="data/chart_engine_research_v2")
    ap.add_argument("--output-root",default="data/chart_engine_research_v4")
    args=ap.parse_args()
    src=ROOT/args.input_root/args.day/"full_market_timeline.csv"
    if not src.is_file(): raise SystemExit(f"Missing V2 timeline: {src}")
    bysym=per_minute(read_csv(src))
    outdir=ROOT/args.output_root/args.day;outdir.mkdir(parents=True,exist_ok=True)
    eps=[];detail=[];miss=[]
    for sym,arr in sorted(bysym.items()):
        idx=None
        for i in range(len(arr)):
            c=confirm(arr,i)
            if c is not None: idx=c;break
        if idx is None:
            miss.append({"symbol":sym,"reason":"NO_V3_CONFIRMATION"});continue
        r=episode(arr,idx)
        row={k:v for k,v in r.items() if k!="detail"}
        row["symbol"]=sym;row["winning_episode"]=r["realized_pp"]>0;row["had_opportunity"]=r["mfe_pp"]>=0.25
        eps.append(row);detail.extend(r["detail"])
    write_csv(outdir/"trade_episodes.csv",eps)
    write_csv(outdir/"trade_episode_detail.csv",detail)
    write_csv(outdir/"no_confirmation_symbols.csv",miss)
    keys=[e for e in eps if e["symbol"] in ("COFORGE","MCX","SBICARD","MOTILALOFS","PREMIERENE","GLENMARK")]
    write_csv(outdir/"key_case_episodes.csv",keys)
    reasons={}
    for e in eps: reasons[e["exit_reason"]]=reasons.get(e["exit_reason"],0)+1
    avg=lambda k: round(sum(float(e[k]) for e in eps)/len(eps),4) if eps else 0
    summary={"mode":"READ_ONLY_TRADE_EPISODE_RESEARCH","day":args.day,"symbols_analysed":len(bysym),"episodes":len(eps),
             "episodes_with_mfe_ge_0_25pp":sum(bool(e["had_opportunity"]) for e in eps),
             "episodes_realized_positive":sum(bool(e["winning_episode"]) for e in eps),
             "winrate_pct":round(100*sum(bool(e["winning_episode"]) for e in eps)/len(eps),2) if eps else 0,
             "opportunity_rate_pct":round(100*sum(bool(e["had_opportunity"]) for e in eps)/len(eps),2) if eps else 0,
             "avg_mfe_pp":avg("mfe_pp"),"avg_mae_pp":avg("mae_pp"),"avg_realized_pp":avg("realized_pp"),
             "avg_capture_efficiency_pct":avg("capture_efficiency_pct"),"exit_reason_counts":reasons,
             "note":"Underlying-state episode research only; not exact option premium P&L."}
    (outdir/"run_manifest.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print("="*108)
    print("APLUS CHART ENGINE V4 - TRADE EPISODE / EXIT ENGINE RESEARCH")
    print("READ ONLY - NO DHAN CALLS - NO PRODUCTION CHANGES")
    print("="*108)
    print("Day                     :",args.day)
    print("Symbols analysed        :",len(bysym))
    print("Confirmed episodes      :",len(eps))
    print("Opportunity >=0.25pp    :",summary["episodes_with_mfe_ge_0_25pp"],f"({summary['opportunity_rate_pct']}%)")
    print("Positive realized exit  :",summary["episodes_realized_positive"],f"({summary['winrate_pct']}%)")
    print("Average MFE pp          :",summary["avg_mfe_pp"])
    print("Average MAE pp          :",summary["avg_mae_pp"])
    print("Average realized pp     :",summary["avg_realized_pp"])
    print("Avg capture efficiency  :",summary["avg_capture_efficiency_pct"],"%")
    print("Exit reasons            :",summary["exit_reason_counts"])
    print("")
    print("KEY CASES")
    for e in keys:
        print(f"{e['symbol']:<12} entry={e['entry_time'][11:16]} exit={e['exit_time'][11:16]} MFE={float(e['mfe_pp']):>6.3f} MAE={float(e['mae_pp']):>6.3f} realized={float(e['realized_pp']):>6.3f} capture={float(e['capture_efficiency_pct']):>6.1f}% reason={e['exit_reason']}")
    print("="*108)

if __name__=="__main__": main()
