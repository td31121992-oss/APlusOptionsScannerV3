from __future__ import annotations

import json, math, os, csv, time, urllib.parse, urllib.request
from collections import defaultdict, deque
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
RESEARCH = ROOT / "data" / "research" / "technical_alerts"
LOGS = ROOT / "data" / "logs"
REFERENCE = ROOT / "data" / "reference"
REPORTS.mkdir(parents=True, exist_ok=True)
RESEARCH.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
REFERENCE.mkdir(parents=True, exist_ok=True)

MARKET_WATCH = REPORTS / "fno_market_watch_latest.json"
INTRADAY = REPORTS / "intraday_movement_latest.json"
LEVELS = REFERENCE / "technical_levels_latest.csv"

LATEST_JSON = REPORTS / "technical_alerts_latest.json"
LATEST_CSV = REPORTS / "technical_alerts_latest.csv"

POLL = 5
TELEGRAM_MIN_GRADE = 99  # research/technical Telegram OFF
TELEGRAM_SERVICE = "CAlphaTrader:Telegram"
TOKEN_ACCOUNT = "bot_token"
CHAT_ACCOUNT = "chat_id"

GRADE = {1:"INFO", 2:"WATCH", 3:"STRONG", 4:"A+ CONFLUENCE"}

def num(v, d=0.0):
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def load_json(p: Path):
    if not p.is_file(): return {}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}

def atomic_json(p: Path, obj):
    t=p.with_suffix(p.suffix+".tmp")
    t.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding="utf-8")
    t.replace(p)

def load_levels():
    out={}
    if not LEVELS.is_file(): return out
    try:
        with LEVELS.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f):
                s=str(r.get("symbol") or "").strip().upper()
                if s: out[s]=r
    except Exception: pass
    return out

def intraday_candidates():
    d=load_json(INTRADAY)
    rows=[]
    if isinstance(d,dict):
        if isinstance(d.get("candidates"),list): rows=d["candidates"]
        elif isinstance(d.get("movement_leaders"),list): rows=d["movement_leaders"]
    return {str(x.get("symbol") or "").upper():x for x in rows if isinstance(x,dict)}

def sector_perf(rows):
    m=defaultdict(list)
    for r in rows: m[str(r.get("sector") or "Other/Industrial")].append(num(r.get("from_open_pct")))
    return {k:sum(v)/len(v) for k,v in m.items() if v}

def round_level(price):
    if price < 100: step=5
    elif price < 500: step=10
    elif price < 2000: step=50
    else: step=100
    return round(price/step)*step, step

def send_telegram(text):
    try:
        import keyring
        token=keyring.get_password(TELEGRAM_SERVICE,TOKEN_ACCOUNT)
        chat=keyring.get_password(TELEGRAM_SERVICE,CHAT_ACCOUNT)
        if not token or not chat: return False
        data=urllib.parse.urlencode({"chat_id":chat,"text":text}).encode()
        req=urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",data=data,method="POST")
        with urllib.request.urlopen(req,timeout=8) as r:
            return 200 <= int(r.status) < 300
    except Exception:
        return False

def alert_msg(a):
    icon="🟢" if a["direction"]=="BULLISH" else "🔴" if a["direction"]=="BEARISH" else "🔔"
    return (
        f"{icon} APLUS {a['grade']}\n"
        f"{a['symbol']} | {a['alert_type']}\n"
        f"Time: {a['time']}\n"
        f"LTP: ₹{a['ltp']:.2f} | Level: ₹{a['level']:.2f}\n"
        f"From 09:15: {a['from_0915_pct']:+.2f}% | Sector: {a['sector_from_0915_pct']:+.2f}%\n"
        f"Rel Vol: {a['relative_volume']:.2f}x | Bias: {a['bias']}\n"
        f"Confluence: {', '.join(a.get('confluence',[])) or '-'}\n"
        f"PAPER/RESEARCH ALERT ONLY"
    )

class Engine:
    def __init__(self):
        self.day=datetime.now(IST).date().isoformat()
        self.events=[]
        self.active={}
        self.baselined=False
        self.tape=defaultdict(lambda: deque(maxlen=7200))
        self.rank_prev={}
        self.last_ltp={}
        self.telegram_sent=set()
        self.day_dir=RESEARCH/self.day
        self.stock_dir=self.day_dir/"stocks"
        self.stock_dir.mkdir(parents=True,exist_ok=True)
        self.all_jsonl=self.day_dir/"all_alerts.jsonl"

    def emit(self, *, now, row, cand, alert_type, direction, level, state="CROSS",
             base_grade=1, details="", confluence=None):
        sym=str(row.get("symbol") or "").upper()
        key=(sym,alert_type)
        ltp=num(row.get("ltp"))
        # Episode de-duplication: event can fire again only after invalidation.
        if self.active.get(key):
            return
        conf=list(confluence or [])
        score=base_grade
        move=num(row.get("from_open_pct")); sp=num(row.get("_sector_pct"))
        rv=num((cand or {}).get("relative_volume"))
        if direction=="BULLISH":
            if move>=1: score+=1
            if sp>=0.35: score+=1
        elif direction=="BEARISH":
            if move<=-1: score+=1
            if sp<=-0.35: score+=1
        if rv>=2: score+=1
        score=max(1,min(4,score))
        bias="CE" if direction=="BULLISH" else "PE" if direction=="BEARISH" else "-"
        ev={
            "event_id":f"{now:%Y%m%d-%H%M%S}-{sym}-{alert_type}",
            "date":self.day,"time":now.strftime("%H:%M:%S"),"timestamp":now.isoformat(),
            "symbol":sym,"sector":str(row.get("sector") or "Other/Industrial"),
            "alert_type":alert_type,"direction":direction,"state":state,
            "level":round(level,4),"ltp":round(ltp,4),
            "deviation_pct":round(((ltp-level)/level*100) if level else 0,4),
            "from_0915_pct":round(move,4),"sector_from_0915_pct":round(sp,4),
            "today_high":num(row.get("day_high")),"today_low":num(row.get("day_low")),
            "today_open":num(row.get("open_0915")),"relative_volume":round(rv,3),
            "vwap":num((cand or {}).get("vwap")),"vwap_distance_pct":num((cand or {}).get("vwap_distance_percent")),
            "grade_score":score,"grade":GRADE[score],"bias":bias,
            "details":details,"confluence":conf,
            "first_touch_time":now.strftime("%H:%M:%S") if state=="TOUCH" else "",
            "cross_time":now.strftime("%H:%M:%S") if state in ("CROSS","CONFIRMED") else "",
            "confirmation_time":now.strftime("%H:%M:%S") if state=="CONFIRMED" else "",
            "invalidation_time":"",
        }
        self.events.insert(0,ev); self.active[key]=ev["event_id"]
        with self.all_jsonl.open("a",encoding="utf-8") as f:
            f.write(json.dumps(ev,ensure_ascii=False)+"\n")
        stock_file=self.stock_dir/f"{sym}.json"
        old=load_json(stock_file)
        arr=old.get("alerts",[]) if isinstance(old,dict) else []
        arr.append(ev)
        atomic_json(stock_file,{"date":self.day,"symbol":sym,"alerts":arr})
        print(ev["time"],ev["grade"],sym,alert_type,direction,f"@ {level:.2f}")
        if score>=TELEGRAM_MIN_GRADE and ev["event_id"] not in self.telegram_sent:
            if send_telegram(alert_msg(ev)): self.telegram_sent.add(ev["event_id"])

    def invalidate(self, sym, alert_type, now):
        key=(sym,alert_type)
        eid=self.active.pop(key,None)
        if not eid:return
        for e in self.events:
            if e.get("event_id")==eid:
                e["invalidation_time"]=now.strftime("%H:%M:%S");break

    def evaluate(self, now, rows, candidates, levels):
        sp=sector_perf(rows)
        # Rank by actual movement from 09:15.
        ups=sorted(rows,key=lambda x:num(x.get("from_open_pct")),reverse=True)[:5]
        dns=sorted(rows,key=lambda x:num(x.get("from_open_pct")))[:5]
        top_up={str(x.get("symbol") or "").upper() for x in ups}
        top_dn={str(x.get("symbol") or "").upper() for x in dns}

        for row in rows:
            sym=str(row.get("symbol") or "").upper()
            if not sym:continue
            sec=str(row.get("sector") or "Other/Industrial")
            row["_sector_pct"]=sp.get(sec,0)
            cand=candidates.get(sym,{})
            ltp=num(row.get("ltp")); op=num(row.get("open_0915")); hi=num(row.get("day_high")); lo=num(row.get("day_low"))
            prev=num(row.get("previous_close")); mv=num(row.get("from_open_pct"))
            rv=num(cand.get("relative_volume")); vwap=num(cand.get("vwap"))
            orh=num(cand.get("opening_range_high")); orl=num(cand.get("opening_range_low"))
            self.tape[sym].append((now.timestamp(),ltp,mv))
            old=self.last_ltp.get(sym,ltp)

            # Opening structure confirmation.
            tol=max(.05,op*.0005) if op else .05
            if op and abs(op-lo)<=tol and mv>=.35:
                self.emit(now=now,row=row,cand=cand,alert_type="OPEN_LOW_CONFIRMED",direction="BULLISH",level=op,state="CONFIRMED",base_grade=2,confluence=["OPEN≈LOW"])
            elif not (op and abs(op-lo)<=tol and mv>=.20):
                self.invalidate(sym,"OPEN_LOW_CONFIRMED",now)
            if op and abs(hi-op)<=tol and mv<=-.35:
                self.emit(now=now,row=row,cand=cand,alert_type="OPEN_HIGH_CONFIRMED",direction="BEARISH",level=op,state="CONFIRMED",base_grade=2,confluence=["OPEN≈HIGH"])
            elif not (op and abs(hi-op)<=tol and mv<=-.20):
                self.invalidate(sym,"OPEN_HIGH_CONFIRMED",now)

            # Opening range.
            if orh>0 and old<=orh<ltp:
                self.emit(now=now,row=row,cand=cand,alert_type="OPENING_RANGE_BREAKOUT",direction="BULLISH",level=orh,base_grade=2,confluence=["OR BREAK"])
            if orh>0 and ltp<orh*.998:self.invalidate(sym,"OPENING_RANGE_BREAKOUT",now)
            if orl>0 and old>=orl>ltp:
                self.emit(now=now,row=row,cand=cand,alert_type="OPENING_RANGE_BREAKDOWN",direction="BEARISH",level=orl,base_grade=2,confluence=["OR BREAK"])
            if orl>0 and ltp>orl*1.002:self.invalidate(sym,"OPENING_RANGE_BREAKDOWN",now)

            # VWAP crosses.
            if vwap>0 and old<=vwap<ltp:
                self.emit(now=now,row=row,cand=cand,alert_type="VWAP_CROSS_UP",direction="BULLISH",level=vwap,base_grade=1,confluence=["VWAP"])
            if vwap>0 and ltp<vwap*.998:self.invalidate(sym,"VWAP_CROSS_UP",now)
            if vwap>0 and old>=vwap>ltp:
                self.emit(now=now,row=row,cand=cand,alert_type="VWAP_CROSS_DOWN",direction="BEARISH",level=vwap,base_grade=1,confluence=["VWAP"])
            if vwap>0 and ltp>vwap*1.002:self.invalidate(sym,"VWAP_CROSS_DOWN",now)

            # Relative volume breakout.
            if rv>=2.0:
                self.emit(now=now,row=row,cand=cand,alert_type="VOLUME_EXPANSION_2X",direction="BULLISH" if mv>0 else "BEARISH",level=ltp,state="CONFIRMED",base_grade=2,confluence=["RVOL>=2x"])
            elif rv<1.6:self.invalidate(sym,"VOLUME_EXPANSION_2X",now)
            if rv>=3.0:
                self.emit(now=now,row=row,cand=cand,alert_type="VOLUME_EXPANSION_3X",direction="BULLISH" if mv>0 else "BEARISH",level=ltp,state="CONFIRMED",base_grade=3,confluence=["RVOL>=3x"])
            elif rv<2.5:self.invalidate(sym,"VOLUME_EXPANSION_3X",now)

            # Gap continuation / failure.
            gap=num(row.get("gap_pct"))
            if gap>=1 and mv>=.5:
                self.emit(now=now,row=row,cand=cand,alert_type="GAP_UP_CONTINUATION",direction="BULLISH",level=op,state="CONFIRMED",base_grade=2,confluence=["GAP UP","FOLLOW THROUGH"])
            elif mv<.2:self.invalidate(sym,"GAP_UP_CONTINUATION",now)
            if gap>=1 and mv<=-.5:
                self.emit(now=now,row=row,cand=cand,alert_type="GAP_UP_FAILURE",direction="BEARISH",level=op,state="CONFIRMED",base_grade=2,confluence=["GAP UP","FADE"])
            elif mv>-.2:self.invalidate(sym,"GAP_UP_FAILURE",now)
            if gap<=-1 and mv<=-.5:
                self.emit(now=now,row=row,cand=cand,alert_type="GAP_DOWN_CONTINUATION",direction="BEARISH",level=op,state="CONFIRMED",base_grade=2,confluence=["GAP DOWN","FOLLOW THROUGH"])
            elif mv>-.2:self.invalidate(sym,"GAP_DOWN_CONTINUATION",now)
            if gap<=-1 and mv>=.5:
                self.emit(now=now,row=row,cand=cand,alert_type="GAP_DOWN_FAILURE",direction="BULLISH",level=op,state="CONFIRMED",base_grade=2,confluence=["GAP DOWN","RECOVERY"])
            elif mv<.2:self.invalidate(sym,"GAP_DOWN_FAILURE",now)

            # Top-5 rank entry.
            prev_rank=self.rank_prev.get(sym,"")
            rank="TOP5_UP" if sym in top_up else "TOP5_DOWN" if sym in top_dn else ""
            if rank and rank!=prev_rank:
                direction="BULLISH" if rank=="TOP5_UP" else "BEARISH"
                self.emit(now=now,row=row,cand=cand,alert_type=f"ENTERED_{rank}",direction=direction,level=ltp,state="CONFIRMED",base_grade=2,confluence=[rank])
            if prev_rank=="TOP5_UP" and rank!="TOP5_UP":self.invalidate(sym,"ENTERED_TOP5_UP",now)
            if prev_rank=="TOP5_DOWN" and rank!="TOP5_DOWN":self.invalidate(sym,"ENTERED_TOP5_DOWN",now)
            self.rank_prev[sym]=rank

            # Acceleration from locally recorded tape: >=0.5% directional move in 5m.
            cutoff=now.timestamp()-300
            hist=[x for x in self.tape[sym] if x[0]>=cutoff]
            if hist and hist[0][1]>0:
                ch=(ltp-hist[0][1])/hist[0][1]*100
                if ch>=.5:self.emit(now=now,row=row,cand=cand,alert_type="ACCELERATION_5M_UP",direction="BULLISH",level=hist[0][1],state="CONFIRMED",base_grade=2,confluence=["5M ACCELERATION"])
                elif ch<.25:self.invalidate(sym,"ACCELERATION_5M_UP",now)
                if ch<=-.5:self.emit(now=now,row=row,cand=cand,alert_type="ACCELERATION_5M_DOWN",direction="BEARISH",level=hist[0][1],state="CONFIRMED",base_grade=2,confluence=["5M ACCELERATION"])
                elif ch>-.25:self.invalidate(sym,"ACCELERATION_5M_DOWN",now)

            # Round-number cross.
            rl,step=round_level(ltp)
            if old<rl<=ltp and abs(ltp-rl)<=step*.2:
                self.emit(now=now,row=row,cand=cand,alert_type="ROUND_LEVEL_BREAKOUT",direction="BULLISH",level=rl,base_grade=1,confluence=["ROUND LEVEL"])
            if old>rl>=ltp and abs(ltp-rl)<=step*.2:
                self.emit(now=now,row=row,cand=cand,alert_type="ROUND_LEVEL_BREAKDOWN",direction="BEARISH",level=rl,base_grade=1,confluence=["ROUND LEVEL"])

            # Optional external/daily technical levels. Active automatically if file is populated.
            lv=levels.get(sym,{})
            for field,label in [
                ("prev_day_high","PREVIOUS_DAY_HIGH"),("prev_day_low","PREVIOUS_DAY_LOW"),
                ("high_5d","5DAY_HIGH"),("low_5d","5DAY_LOW"),("high_10d","10DAY_HIGH"),("low_10d","10DAY_LOW"),
                ("high_30d","30DAY_HIGH"),("low_30d","30DAY_LOW"),("high_90d","90DAY_HIGH"),("low_90d","90DAY_LOW"),
                ("high_52w","52W_HIGH"),("low_52w","52W_LOW"),("ema20","EMA20"),("sma50","SMA50"),
                ("sma100","SMA100"),("sma200","SMA200"),("supertrend_level","SUPERTREND")
            ]:
                level=num(lv.get(field))
                if level<=0:continue
                if old<=level<ltp:
                    self.emit(now=now,row=row,cand=cand,alert_type=f"{label}_BREAKOUT",direction="BULLISH",level=level,base_grade=2,confluence=[label])
                if old>=level>ltp:
                    self.emit(now=now,row=row,cand=cand,alert_type=f"{label}_BREAKDOWN",direction="BEARISH",level=level,base_grade=2,confluence=[label])

            self.last_ltp[sym]=ltp

    def save(self, now):
        latest=self.events[:500]
        payload={"generated_at":now.isoformat(),"date":self.day,"mode":"PAPER_RESEARCH_ALERTS_ONLY",
                 "telegram_min_grade":"STRONG","total_alerts":len(self.events),"alerts":latest}
        atomic_json(LATEST_JSON,payload)
        fields=["date","time","symbol","sector","grade","alert_type","direction","state","ltp","level","deviation_pct",
                "from_0915_pct","sector_from_0915_pct","relative_volume","vwap","bias","first_touch_time","cross_time",
                "confirmation_time","invalidation_time","details"]
        with LATEST_CSV.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(latest)

    def run(self):
        print("="*86)
        print("APlus Real-Time Technical Alert Engine")
        print("PAPER/RESEARCH ALERTS ONLY - NO ORDER AUTHORITY")
        print("Uses existing APlus reports. No additional Dhan requests.")
        print("="*86)
        while True:
            now=datetime.now(IST)
            if now.date().isoformat()!=self.day:return
            if now.time()<dtime(9,15):time.sleep(5);continue
            if now.time()>dtime(15,35):
                self.save(now);return
            mw=load_json(MARKET_WATCH)
            rows=[x for x in (mw.get("rows",[]) if isinstance(mw,dict) else []) if isinstance(x,dict)]
            if not rows:time.sleep(POLL);continue
            self.evaluate(now,rows,intraday_candidates(),load_levels())
            self.save(now);time.sleep(POLL)

if __name__=="__main__":
    Engine().run()
