from __future__ import annotations
import csv,json,math,itertools
from collections import defaultdict
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parent;REPORTS=ROOT/"data"/"reports";CHART_BASE=ROOT/"data"/"chart_history";V62=ROOT/"data"/"leadership_engine_v6_2";OUT=ROOT/"data"/"leadership_engine_v6_3"
def f(v,d=None):
    try:
        x=float(v);return x if math.isfinite(x) else d
    except Exception:return d
def latest_day():
    p=REPORTS/"fno_market_watch_latest.json"
    try:return str(json.loads(p.read_text(encoding="utf-8")).get("generated_at") or "")[:10]
    except Exception:return datetime.now().date().isoformat()
def readcsv(p):
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def hist(day):
    by=defaultdict(list);p=CHART_BASE/day/"market_watch_1m.csv"
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        for r in csv.DictReader(h):
            s=str(r.get("symbol") or "").upper().strip();m=str(r.get("minute") or "")
            if s and m:by[s].append({"minute":m,"move":f(r.get("from_open_pct"),0.0)})
    for s in by:by[s].sort(key=lambda z:z["minute"])
    return by
def main():
    day=latest_day();src=V62/day/"v6_2_entry_exit_forensic.csv"
    if not src.exists():raise SystemExit(f"Missing {src}. Run V6.2 first.")
    setups=readcsv(src);hmap=hist(day);paths=[]
    for e in setups:
        h=hmap.get(e["symbol"],[]);idx={x["minute"]:i for i,x in enumerate(h)};i=idx.get(e["signal_minute"])
        if i is None:continue
        sign=1 if e["side"]=="CE" else -1;entry=h[i]["move"]
        path=[{"j":j,"minute":z["minute"],"move":(z["move"]-entry)*sign} for j,z in enumerate(h[i:min(len(h),i+91)])]
        paths.append((e,path))
    configs=[]
    for act,give,stop,stall_n,stall_ret in itertools.product([.15,.20,.25,.30,.40,.50],[.08,.12,.15,.18,.22,.30,.40],[.15,.20,.25,.30,.40],[3,4,5,7],[.08,.12,.15,.20,.25]):
        results=[]
        for e,path in paths:
            peak=0;no_new=0;chosen=None
            for z in path:
                m=z["move"]
                if m>peak+1e-12:peak=m;no_new=0
                else:no_new+=1
                if m<=-stop:chosen=("HARD_STOP",z,peak);break
                if peak>=act and m<=peak-give:chosen=("PROFIT_TRAIL",z,peak);break
                if peak>=act and no_new>=stall_n and m<=peak-stall_ret:chosen=("STALL",z,peak);break
            if chosen is None:chosen=("TIME_HORIZON",path[-1],peak)
            reason,z,peak=chosen;mfe=max(x["move"] for x in path);real=z["move"];cap=real/mfe*100 if mfe>0 else 0
            results.append({"symbol":e["symbol"],"signal_minute":e["signal_minute"],"side":e["side"],"reason":reason,"exit_minute":z["minute"],"realized":real,"mfe":mfe,"capture":cap})
        vals=[r["realized"] for r in results];pos=sum(v>0 for v in vals);w=[r for r in results if r["mfe"]>=.30];capavg=sum(max(-50,min(100,r["capture"])) for r in w)/len(w) if w else 0;avg=sum(vals)/len(vals)
        score=avg*120+(pos/len(vals)*100)*.7+capavg*.35-sum(v<=-.25 for v in vals)*4
        configs.append({"activation":act,"giveback":give,"hard_stop":stop,"stall_minutes":stall_n,"stall_retrace":stall_ret,"trades":len(vals),"positive_exit_pct":round(pos/len(vals)*100,2),"avg_realized_pct":round(avg,4),"avg_winner_capture_pct":round(capavg,2),"large_losses":sum(v<=-.25 for v in vals),"score":round(score,3),"results":results})
    configs.sort(key=lambda x:x["score"],reverse=True);best=configs[0];od=OUT/day;od.mkdir(parents=True,exist_ok=True)
    clean=[{k:v for k,v in c.items() if k!="results"} for c in configs]
    with (od/"v6_3_exit_matrix.csv").open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(clean[0].keys()));w.writeheader();w.writerows(clean)
    with (od/"v6_3_best_trade_exits.csv").open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(best["results"][0].keys()));w.writeheader();w.writerows(best["results"])
    manifest={k:v for k,v in best.items() if k!="results"};manifest.update({"day":day,"research_only":True,"production_changes":False,"dhan_calls":False})
    (od/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print("="*110);print("APLUS LEADERSHIP V6.3 EXIT OPTIMIZATION");print("="*110)
    for k,v in manifest.items():print(f"{k:<28}: {v}")
    print("\nBEST TRADE EXITS")
    for r in best["results"]:print(f"{r['signal_minute']} {r['symbol']:<14} {r['side']} MFE={r['mfe']:+.3f}% exit={r['realized']:+.3f}% capture={r['capture']:+.1f}% {r['reason']}@{r['exit_minute']}")
    print("\nResearch only. One-day optimum requires forward paper validation.")
if __name__=="__main__":main()
