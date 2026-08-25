from __future__ import annotations
import csv, json, math
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REPORT=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
OUTCSV=ROOT/"data"/"reports"/"time_relative_ranking_latest.csv"
OUTJSON=ROOT/"data"/"reports"/"time_relative_ranking_latest.json"
HIST=ROOT/"data"/"time_relative_rank_history"
STATE=ROOT/"data"/"cache"/"time_relative_ranking_state.json"

WINDOW_MINUTES=15
TOP_K=25

def f(v,default=0.0):
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def load_json(p,default):
    try:return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:return default

def atomic_json(p,payload):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+".tmp")
    tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    tmp.replace(p)

def write_csv(p,rows,fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+".tmp")
    with tmp.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    tmp.replace(p)

def rank_map(rows,key,reverse=True):
    ordered=sorted(rows,key=lambda r:f(r.get(key)),reverse=reverse)
    return {str(r.get("symbol","")).upper():i+1 for i,r in enumerate(ordered)}

def main():
    d=load_json(REPORT,{})
    rows=d.get("rows",[]) or []
    if not rows:
        raise SystemExit("NO MARKET WATCH ROWS")

    generated=str(d.get("generated_at") or datetime.now().isoformat())
    try: ts=datetime.fromisoformat(generated)
    except Exception: ts=datetime.now()
    day=ts.date().isoformat()
    minute=ts.strftime("%H:%M")

    # Current rankings from open and from previous close.
    up_rank=rank_map(rows,"from_open_pct",True)
    down_rank=rank_map(rows,"from_open_pct",False)

    state=load_json(STATE,{"history":{}})
    hist=state.setdefault("history",{})

    result=[]
    for r in rows:
        sym=str(r.get("symbol") or "").upper()
        if not sym: continue
        move=f(r.get("from_open_pct"))
        direction="UP" if move>=0 else "DOWN"
        rank=up_rank[sym] if direction=="UP" else down_rank[sym]

        seq=hist.setdefault(sym,[])
        seq.append({"ts":generated,"minute":minute,"rank":rank,"move":move,"direction":direction})
        seq[:] = seq[-40:]

        prev_5=seq[-6] if len(seq)>=6 else seq[0]
        prev_10=seq[-11] if len(seq)>=11 else seq[0]
        prev_15=seq[-16] if len(seq)>=16 else seq[0]

        def accel(prev):
            if prev.get("direction")!=direction: return 0
            return int(prev.get("rank",rank))-rank

        a5,a10,a15=accel(prev_5),accel(prev_10),accel(prev_15)
        move5=move-f(prev_5.get("move"))
        move10=move-f(prev_10.get("move"))
        move15=move-f(prev_15.get("move"))

        # Research score only. Ranking acceleration dominates; price acceleration confirms.
        rank_accel_score=max(0,a5)*1.5+max(0,a10)*0.8+max(0,a15)*0.4
        price_accel_score=max(0,move5 if direction=="UP" else -move5)*12
        leadership_score=max(0,26-rank)*1.2
        score=round(rank_accel_score+price_accel_score+leadership_score,2)

        label="STABLE"
        if a5>=10 or (a5>=5 and abs(move5)>=0.20): label="RAPID_RISER"
        elif a5>=3 or a10>=8: label="IMPROVING"
        elif a5<=-8: label="FADING"

        result.append({
            "timestamp":generated,"symbol":sym,"sector":r.get("sector",""),
            "direction":direction,"from_open_pct":round(move,4),
            "current_rank":rank,"rank_change_5m":a5,"rank_change_10m":a10,"rank_change_15m":a15,
            "move_change_5m_pct":round(move5,4),"move_change_10m_pct":round(move10,4),"move_change_15m_pct":round(move15,4),
            "rank_acceleration_state":label,"rank_acceleration_score":score,
            "ltp":r.get("ltp"),"open_0915":r.get("open_0915"),
        })

    result.sort(key=lambda x:x["rank_acceleration_score"],reverse=True)
    for i,r in enumerate(result,1): r["acceleration_rank"]=i

    fields=list(result[0].keys())
    write_csv(OUTCSV,result,fields)
    atomic_json(OUTJSON,{
        "generated_at":generated,
        "count":len(result),
        "top_accelerating":result[:TOP_K],
        "rows":result,
        "research_only":True,
    })
    STATE.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(STATE,state)

    daydir=HIST/day
    daydir.mkdir(parents=True,exist_ok=True)
    archive=daydir/f"rank_{ts.strftime('%H%M')}.csv"
    write_csv(archive,result,fields)

    print("="*100)
    print("APLUS TIME-RELATIVE RANKING ENGINE - RESEARCH ONLY")
    print("Timestamp:",generated)
    print("Stocks:",len(result))
    print()
    print("TOP 15 RANK-ACCELERATION")
    for r in result[:15]:
        print(f"{r['symbol']:<14} {r['direction']:<4} rank={r['current_rank']:>3}  5m={r['rank_change_5m']:>4} 10m={r['rank_change_10m']:>4} 15m={r['rank_change_15m']:>4} move5={r['move_change_5m_pct']:>7.3f}% score={r['rank_acceleration_score']:>7.2f} {r['rank_acceleration_state']}")
    print()
    print("Files:")
    print(" ",OUTCSV)
    print(" ",OUTJSON)
    print(" ",archive)
    print("NO scanner/trading files changed.")
    print("="*100)

if __name__=="__main__": main()
