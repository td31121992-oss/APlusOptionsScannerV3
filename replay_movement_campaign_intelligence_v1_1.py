from __future__ import annotations
import csv,json,argparse
from collections import defaultdict,deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
IST=ZoneInfo("Asia/Kolkata")
VERSION="V1.1_DIRECTION_PERSISTENCE"

def f(v,d=0.0):
    try:return float(v)
    except:return d

def loadc(p):
    if not p.exists():return []
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--day",required=True)
    x=a.parse_args()
    day=x.day

    merged={}
    for p in [
        ROOT/"data"/"chart_history"/day/"market_watch_1m.csv",
        ROOT/"data"/"breakout_evidence"/day/"market_watch_1m_ohlcv.csv",
    ]:
        for r in loadc(p):
            s=str(r.get("symbol") or "").upper()
            tm=str(r.get("minute") or "")
            if not s or not tm:continue
            merged[(s,tm)]={
                "symbol":s,"time":tm,
                "price":f(r.get("close_1m",r.get("ltp"))),
                "move":f(r.get("from_open_pct"))
            }

    bytime=defaultdict(list)
    for r in merged.values():bytime[r["time"]].append(r)

    tape=defaultdict(lambda:deque(maxlen=240))
    first={}
    detections={}
    final={}
    last_direction={}
    streak=defaultdict(int)

    for tm in sorted(bytime):
        now=datetime.fromisoformat(day+"T"+tm+":00").replace(tzinfo=IST)
        rows=bytime[tm]
        ups=sorted([r for r in rows if r["move"]>0],key=lambda r:r["move"],reverse=True)
        downs=sorted([r for r in rows if r["move"]<0],key=lambda r:r["move"])
        ur={r["symbol"]:i+1 for i,r in enumerate(ups)}
        dr={r["symbol"]:i+1 for i,r in enumerate(downs)}

        for r in rows:
            s,px,mv=r["symbol"],r["price"],r["move"]
            direction="UP" if mv>0 else ("DOWN" if mv<0 else "FLAT")
            tape[s].append((now,px,mv))
            final[s]={"symbol":s,"direction":direction,"final_move_pct":mv}

            if direction=="FLAT":
                last_direction[s]="FLAT"
                continue

            old=last_direction.get(s)
            if old==direction:
                streak[(s,direction)]+=1
            else:
                if old in {"UP","DOWN"}:
                    streak[(s,old)]=0
                streak[(s,direction)]=1
                last_direction[s]=direction

            if abs(mv)>=.45 and (s,direction) not in first:
                first[(s,direction)]=now

            rank=ur.get(s,999) if direction=="UP" else dr.get(s,999)
            rr=list(tape[s])

            def mom(n):
                cutoff=now.timestamp()-n*60
                oldrow=next((q for q in rr if q[0].timestamp()>=cutoff),rr[0])
                return ((px-oldrow[1])/oldrow[1]*100.0) if oldrow[1] else 0.0

            m5,m10=mom(5),mom(10)
            age=((now-first[(s,direction)]).total_seconds()/60.0) if (s,direction) in first else 0.0
            moves=[q[2] for q in rr]
            fav=max(moves) if direction=="UP" else min(moves)
            ret=(abs(mv)/abs(fav)*100.0) if fav else 0.0
            aligned=(m5>.08 and m10>.12) if direction=="UP" else (m5<-.08 and m10<-.12)
            accel=abs(m5)>=.12 and abs(m5)>=abs(m10)/2.0

            score=(30 if rank<=5 else 20 if rank<=10 else 0)
            score+=(20 if 0<age<=35 else 10 if 0<age<=60 else 0)
            score+=(20 if ret>=80 else 10 if ret>=65 else 0)
            score+=(15 if aligned else 0)
            score+=(10 if accel else 0)
            score+=(5 if abs(mv)>=.7 else 0)

            # Direction persistence is mandatory.
            if streak[(s,direction)]<3:
                score=min(score,55)

            key=(s,direction)
            if (
                streak[(s,direction)]>=3
                and score>=70
                and age<=60
                and key not in detections
            ):
                detections[key]={
                    "time":tm,"score":score,"move":mv,"rank":rank,
                    "direction_streak":streak[(s,direction)]
                }

    out=[]
    for r in sorted(final.values(),key=lambda z:abs(z["final_move_pct"]),reverse=True)[:40]:
        final_dir=r["direction"]
        d=detections.get((r["symbol"],final_dir))
        opposite="DOWN" if final_dir=="UP" else "UP"
        od=detections.get((r["symbol"],opposite))
        out.append({
            **r,
            "version":VERSION,
            "first_matching_direction_campaign_time":d["time"] if d else "",
            "first_matching_direction_score":d["score"] if d else 0,
            "move_at_matching_detection_pct":d["move"] if d else None,
            "rank_at_matching_detection":d["rank"] if d else None,
            "direction_streak_at_detection":d["direction_streak"] if d else 0,
            "opposite_direction_campaign_seen":bool(od),
            "opposite_direction_first_time":od["time"] if od else "",
        })

    odir=ROOT/"data"/"reports"/"movement_campaign_replay_v1_1"/day
    odir.mkdir(parents=True,exist_ok=True)
    (odir/"campaign_replay_summary.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    with (odir/"campaign_replay_summary.csv").open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(out[0].keys()) if out else ["symbol"])
        w.writeheader();w.writerows(out)

    print("="*118)
    print("MOVEMENT CAMPAIGN INTELLIGENCE V1.1 REPLAY - DIRECTION PERSISTENCE",day)
    for r in out:
        print(r)
    print("OUTPUT:",odir)

if __name__=="__main__":main()
