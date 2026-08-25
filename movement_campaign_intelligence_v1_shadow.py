from __future__ import annotations
import csv, json, time, argparse
from collections import defaultdict, deque
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
IST=ZoneInfo("Asia/Kolkata")
MARKET=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
OUTDIR=ROOT/"data"/"reports"/"movement_campaign_shadow"
HISTDIR=ROOT/"data"/"movement_campaign_shadow_history"
VERSION="V1.1_DIRECTION_PERSISTENCE"

def f(v,d=0.0):
    try:return float(v)
    except:return d

def load_json(p):
    try:return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except:return {}

class Book:
    def __init__(self):
        self.tape=defaultdict(lambda:deque(maxlen=240))
        self.first_move={}
        self.top5_hits=defaultdict(int)
        self.direction_streak=defaultdict(int)
        self.last_direction={}
        self.confirmed_direction_start={}

    def _update_direction_streak(self, symbol, direction, now):
        old=self.last_direction.get(symbol)
        if old==direction:
            self.direction_streak[(symbol,direction)] += 1
        else:
            if old:
                self.direction_streak[(symbol,old)] = 0
            self.direction_streak[(symbol,direction)] = 1
            self.last_direction[symbol]=direction
            self.confirmed_direction_start.pop((symbol,direction),None)

        streak=self.direction_streak[(symbol,direction)]
        if streak>=3 and (symbol,direction) not in self.confirmed_direction_start:
            self.confirmed_direction_start[(symbol,direction)] = now
        return streak

    def update(self, now, source_rows):
        norm=[]
        for r in source_rows:
            s=str(r.get("symbol") or "").upper()
            px=f(r.get("ltp"))
            mv=f(r.get("from_open_pct",r.get("move_from_open_percent")))
            if not s or px<=0: continue
            self.tape[s].append((now,px,mv))
            direction="UP" if mv>0 else ("DOWN" if mv<0 else "FLAT")
            if direction=="FLAT":
                self.last_direction[s]=direction
                norm.append((s,px,mv,direction,0))
                continue
            streak=self._update_direction_streak(s,direction,now)
            if abs(mv)>=0.45 and (s,direction) not in self.first_move:
                self.first_move[(s,direction)]=now
            norm.append((s,px,mv,direction,streak))

        ups=sorted([x for x in norm if x[3]=="UP"],key=lambda x:x[2],reverse=True)
        downs=sorted([x for x in norm if x[3]=="DOWN"],key=lambda x:x[2])
        ur={x[0]:i+1 for i,x in enumerate(ups)}
        dr={x[0]:i+1 for i,x in enumerate(downs)}

        result=[]
        for s,px,mv,direction,streak in norm:
            if direction=="FLAT":
                result.append({
                    "version":VERSION,"timestamp":now.isoformat(),"symbol":s,"direction":"FLAT",
                    "ltp":round(px,4),"from_open_pct":round(mv,4),
                    "direction_streak":0,"direction_confirmed":False,
                    "rank_direction":999,"top5_hits":self.top5_hits[s],
                    "movement_start":"","movement_age_min":0.0,
                    "m5_pct":0.0,"m10_pct":0.0,"m15_pct":0.0,
                    "retention_pct":0.0,"early_campaign_score":0.0,
                    "move_maturity_score":0.0,"stage":"NO_CAMPAIGN"
                })
                continue

            rank=ur.get(s,999) if direction=="UP" else dr.get(s,999)
            if rank<=5:self.top5_hits[s]+=1
            rr=list(self.tape[s])

            def mom(minutes):
                cutoff=now.timestamp()-minutes*60
                old=next((x for x in rr if x[0].timestamp()>=cutoff),rr[0])
                return ((px-old[1])/old[1]*100.0) if old[1] else 0.0

            m5,m10,m15=mom(5),mom(10),mom(15)
            start=self.first_move.get((s,direction))
            age=((now-start).total_seconds()/60.0) if start else 0.0
            moves=[x[2] for x in rr]
            fav=max(moves) if direction=="UP" else min(moves)
            retention=(abs(mv)/abs(fav)*100.0) if fav else 0.0

            direction_confirmed = streak>=3
            aligned=(m5>0.08 and m10>0.12) if direction=="UP" else (m5<-0.08 and m10<-0.12)
            accel=(abs(m5)>=0.12 and abs(m5)>=abs(m10)/2.0)

            early=0
            early += 30 if rank<=5 else (20 if rank<=10 else 0)
            early += 20 if 0<age<=35 else (10 if 0<age<=60 else 0)
            early += 20 if retention>=80 else (10 if retention>=65 else 0)
            early += 15 if aligned else 0
            early += 10 if accel else 0
            early += 5 if abs(mv)>=0.7 else 0

            # V1.1: campaign can never be EARLY until direction persisted.
            if not direction_confirmed:
                early=min(early,55)

            weakening=(direction=="UP" and m5<=0) or (direction=="DOWN" and m5>=0)
            mature=min(100,
                min(35,abs(mv)*10)+
                min(30,age/2.0)+
                (20 if weakening else 0)+
                (15 if retention<70 else 0)
            )

            if direction_confirmed and early>=70 and age<=60:
                stage=f"EARLY_CAMPAIGN_{direction}"
            elif mature>=65:
                stage=f"MATURE_OR_CHASE_RISK_{direction}"
            elif abs(mv)>=0.45:
                stage=f"DEVELOPING_CAMPAIGN_{direction}"
            else:
                stage="NO_CAMPAIGN"

            result.append({
                "version":VERSION,"timestamp":now.isoformat(),"symbol":s,"direction":direction,
                "ltp":round(px,4),"from_open_pct":round(mv,4),
                "direction_streak":streak,"direction_confirmed":direction_confirmed,
                "rank_direction":rank,"top5_hits":self.top5_hits[s],
                "movement_start":start.isoformat() if start else "",
                "movement_age_min":round(age,2),
                "m5_pct":round(m5,4),"m10_pct":round(m10,4),"m15_pct":round(m15,4),
                "retention_pct":round(retention,2),
                "early_campaign_score":round(early,2),
                "move_maturity_score":round(mature,2),
                "stage":stage
            })
        return result

def read_market():
    obj=load_json(MARKET)
    rows=obj.get("rows",[]) if isinstance(obj,dict) else []
    try:now=datetime.fromisoformat(str(obj.get("generated_at"))).astimezone(IST)
    except:now=datetime.now(IST)
    return now,[r for r in rows if isinstance(r,dict)]

def persist(now, rows):
    OUTDIR.mkdir(parents=True,exist_ok=True)
    (OUTDIR/"movement_campaign_shadow_latest.json").write_text(
        json.dumps({"version":VERSION,"as_of":now.isoformat(),"rows":rows},indent=2),
        encoding="utf-8"
    )
    top=sorted(rows,key=lambda r:r["early_campaign_score"],reverse=True)[:30]
    if top:
        with (OUTDIR/"movement_campaign_shadow_latest.csv").open("w",encoding="utf-8-sig",newline="") as h:
            w=csv.DictWriter(h,fieldnames=list(top[0].keys()));w.writeheader();w.writerows(top)

    day=now.date().isoformat()
    p=HISTDIR/day/"campaign_history_v1_1.csv"
    p.parent.mkdir(parents=True,exist_ok=True)
    if rows:
        exists=p.exists()
        with p.open("a",encoding="utf-8-sig",newline="") as h:
            w=csv.DictWriter(h,fieldnames=list(rows[0].keys()))
            if not exists:w.writeheader()
            w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--interval",type=int,default=30)
    ap.add_argument("--once",action="store_true")
    args=ap.parse_args()
    print("="*110)
    print("APlus Movement Campaign Intelligence V1.1 - DIRECTION PERSISTENCE - SHADOW ONLY")
    print("3 consecutive same-direction observations required before EARLY_CAMPAIGN")
    print("ZERO Dhan calls - ZERO trade decision changes")
    print("="*110)

    b=Book()
    while True:
        now,rows=read_market()
        result=b.update(now,rows)
        persist(now,result)
        leaders=sorted(result,key=lambda r:r["early_campaign_score"],reverse=True)[:5]
        print(now.strftime("%H:%M:%S"),[
            (x["symbol"],x["stage"],x["direction_streak"],x["early_campaign_score"],x["from_open_pct"])
            for x in leaders
        ])
        if args.once:return
        if datetime.now(IST).time()>=dtime(15,36):return
        time.sleep(max(10,args.interval))

if __name__=="__main__":main()
