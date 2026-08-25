from __future__ import annotations
import csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REPORT=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
CHART_BASE=ROOT/"data"/"chart_history"
OUTCSV=ROOT/"data"/"reports"/"time_relative_ranking_v2_latest.csv"
OUTJSON=ROOT/"data"/"reports"/"time_relative_ranking_v2_latest.json"
HISTOUT=ROOT/"data"/"time_relative_rank_history_v2"

TARGETS=["BDL","CDSL","GVT&D","POWERINDIA","POWERGRID"]

def f(v,default=0.0):
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def parse_ts(v):
    try:return datetime.fromisoformat(str(v))
    except Exception:return None

def load_latest():
    try:return json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    except Exception:return {}

def read_chart_day(day):
    p=CHART_BASE/day/"market_watch_1m.csv"
    if not p.exists(): return {}
    by_minute=defaultdict(list)
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        for r in csv.DictReader(h):
            sym=str(r.get("symbol") or "").upper().strip()
            minute=str(r.get("minute") or "").strip()
            if not sym or not minute: continue
            by_minute[minute].append({
                "symbol":sym,
                "sector":r.get("sector",""),
                "from_open_pct":f(r.get("from_open_pct")),
                "ltp":r.get("ltp",""),
                "open_0915":r.get("open_0915",""),
            })
    return dict(by_minute)

def ranks_for(rows):
    up=sorted(rows,key=lambda r:f(r["from_open_pct"]),reverse=True)
    down=sorted(rows,key=lambda r:f(r["from_open_pct"]))
    ur={r["symbol"]:i+1 for i,r in enumerate(up)}
    dr={r["symbol"]:i+1 for i,r in enumerate(down)}
    return ur,dr

def nearest_prior(history, idx, minutes_back):
    target=idx-minutes_back
    return history[target] if target>=0 else history[0]

def build(day):
    by_minute=read_chart_day(day)

    # Add latest report as a fresh minute only if it is not already in chart history.
    latest=load_latest()
    gen=str(latest.get("generated_at") or "")
    ts=parse_ts(gen)
    if ts and ts.date().isoformat()==day:
        minute=ts.strftime("%H:%M")
        if minute not in by_minute:
            rows=[]
            for r in latest.get("rows",[]) or []:
                sym=str(r.get("symbol") or "").upper().strip()
                if sym:
                    rows.append({
                        "symbol":sym,
                        "sector":r.get("sector",""),
                        "from_open_pct":f(r.get("from_open_pct")),
                        "ltp":r.get("ltp",""),
                        "open_0915":r.get("open_0915",""),
                    })
            if rows: by_minute[minute]=rows

    minutes=sorted(by_minute.keys())
    if not minutes:
        raise SystemExit(f"NO HISTORY FOUND for {day}. Expected data\\chart_history\\{day}\\market_watch_1m.csv")

    timeline=defaultdict(list)

    for minute in minutes:
        rows=by_minute[minute]
        ur,dr=ranks_for(rows)
        for r in rows:
            sym=r["symbol"]; move=f(r["from_open_pct"])
            direction="UP" if move>=0 else "DOWN"
            rank=ur[sym] if direction=="UP" else dr[sym]
            timeline[sym].append({
                "minute":minute,"rank":rank,"move":move,"direction":direction,
                "sector":r.get("sector",""),"ltp":r.get("ltp",""),"open_0915":r.get("open_0915",""),
            })

    latest_rows=[]
    target_events={}

    for sym,h in timeline.items():
        h.sort(key=lambda x:x["minute"])
        states=[]
        for i,x in enumerate(h):
            p5=nearest_prior(h,i,5); p10=nearest_prior(h,i,10); p15=nearest_prior(h,i,15)

            def accel(prev):
                return (int(prev["rank"])-int(x["rank"])) if prev["direction"]==x["direction"] else 0

            a5,a10,a15=accel(p5),accel(p10),accel(p15)
            sign=1 if x["direction"]=="UP" else -1
            m5=(x["move"]-p5["move"])*sign
            m10=(x["move"]-p10["move"])*sign
            m15=(x["move"]-p15["move"])*sign

            score=max(0,a5)*1.5+max(0,a10)*0.8+max(0,a15)*0.4+max(0,m5)*12+max(0,26-x["rank"])*1.2
            label="STABLE"
            if a5>=10 or (a5>=5 and m5>=0.20): label="RAPID_RISER"
            elif a5>=3 or a10>=8: label="IMPROVING"
            elif a5<=-8: label="FADING"

            states.append({
                "minute":x["minute"],"symbol":sym,"sector":x["sector"],"direction":x["direction"],
                "from_open_pct":round(x["move"],4),"current_rank":x["rank"],
                "rank_change_5m":a5,"rank_change_10m":a10,"rank_change_15m":a15,
                "move_change_5m_pct":round(m5,4),"move_change_10m_pct":round(m10,4),"move_change_15m_pct":round(m15,4),
                "rank_acceleration_state":label,"rank_acceleration_score":round(score,2),
            })

        latest_rows.append(states[-1])

        if sym in TARGETS:
            first_improving=next((z for z in states if z["rank_acceleration_state"] in ("IMPROVING","RAPID_RISER")),None)
            first_top10=next((z for z in states if z["direction"]=="UP" and z["current_rank"]<=10),None)
            first_top5=next((z for z in states if z["direction"]=="UP" and z["current_rank"]<=5),None)
            best=max(states,key=lambda z:z["rank_acceleration_score"])
            target_events[sym]={
                "first_improving":first_improving,
                "first_top10":first_top10,
                "first_top5":first_top5,
                "best_acceleration":best,
                "latest":states[-1],
            }

        daydir=HISTOUT/day
        daydir.mkdir(parents=True,exist_ok=True)
        if sym in TARGETS:
            p=daydir/f"{sym.replace('&','AND')}_rank_timeline.csv"
            with p.open("w",encoding="utf-8-sig",newline="") as fh:
                w=csv.DictWriter(fh,fieldnames=list(states[0].keys()))
                w.writeheader();w.writerows(states)

    latest_rows.sort(key=lambda x:x["rank_acceleration_score"],reverse=True)
    for i,r in enumerate(latest_rows,1):r["acceleration_rank"]=i

    OUTCSV.parent.mkdir(parents=True,exist_ok=True)
    with OUTCSV.open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=list(latest_rows[0].keys()))
        w.writeheader();w.writerows(latest_rows)

    OUTJSON.write_text(json.dumps({
        "day":day,"minutes_replayed":len(minutes),"symbols":len(timeline),
        "target_events":target_events,"rows":latest_rows,"research_only":True
    },indent=2,ensure_ascii=False),encoding="utf-8")

    print("="*118)
    print("APLUS TIME-RELATIVE RANKING V2 - HISTORICAL REPLAY + LIVE LATEST")
    print("Day:",day,"Minutes replayed:",len(minutes),"Symbols:",len(timeline))
    print("="*118)
    print()
    print("TARGET FORENSICS")
    for sym in TARGETS:
        e=target_events.get(sym)
        if not e:
            print(f"{sym:<14} NO HISTORY")
            continue
        def fmt(z):
            if not z:return "NOT REACHED"
            return f"{z['minute']} rank={z['current_rank']} move={z['from_open_pct']:+.3f}% 5mRank={z['rank_change_5m']:+d} 5mMove={z['move_change_5m_pct']:+.3f}% state={z['rank_acceleration_state']}"
        print(f"{sym}")
        print("  first improving :",fmt(e["first_improving"]))
        print("  first top-10    :",fmt(e["first_top10"]))
        print("  first top-5     :",fmt(e["first_top5"]))
        print("  best acceleration:",fmt(e["best_acceleration"]))
        print("  latest          :",fmt(e["latest"]))
    print()
    print("TOP 15 CURRENT ACCELERATION")
    for r in latest_rows[:15]:
        print(f"{r['symbol']:<14} {r['direction']:<4} rank={r['current_rank']:>3} 5m={r['rank_change_5m']:>+4} 10m={r['rank_change_10m']:>+4} move5={r['move_change_5m_pct']:>+7.3f}% score={r['rank_acceleration_score']:>7.2f} {r['rank_acceleration_state']}")
    print()
    print("Research only. No scanner/trading files changed.")
    print("="*118)

if __name__=="__main__":
    d=load_latest()
    ts=parse_ts(d.get("generated_at"))
    day=ts.date().isoformat() if ts else datetime.now().date().isoformat()
    build(day)
