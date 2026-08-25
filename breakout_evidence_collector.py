from __future__ import annotations
import csv,json,time
from datetime import datetime,time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
REPORT=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
BASE=ROOT/"data"/"breakout_evidence"
IST=ZoneInfo("Asia/Kolkata")
FIELDS=["timestamp","date","minute","symbol","security_id","sector","open_1m","high_1m","low_1m","close_1m","volume_cumulative","volume_delta_1m","average_price","open_0915","previous_close","from_open_pct","day_high","day_low","range_position_pct","direction","samples_in_minute"]

current_minute=""
bars={}
previous_volume={}

def f(v,d=0.0):
    try:return float(v)
    except Exception:return d

def flush(minute_key):
    global bars
    if not bars:return
    day=minute_key[:10];p=BASE/day/"market_watch_1m_ohlcv.csv";p.parent.mkdir(parents=True,exist_ok=True);exists=p.exists()
    with p.open("a",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS,extrasaction="ignore")
        if not exists:w.writeheader()
        for row in bars.values():w.writerow(row)
    bars={}

def cycle():
    global current_minute,bars,previous_volume
    if not REPORT.exists():return
    try:o=json.loads(REPORT.read_text(encoding="utf-8"))
    except Exception:return
    rows=o.get("rows",[]) if isinstance(o,dict) else []
    if not rows:return
    try:ts=datetime.fromisoformat(str(o.get("generated_at") or "")).astimezone(IST)
    except Exception:ts=datetime.now(IST)
    minute=ts.strftime("%Y-%m-%dT%H:%M")
    if current_minute and minute!=current_minute:flush(current_minute)
    current_minute=minute
    for r in rows:
        sym=str(r.get("symbol") or "").upper();price=f(r.get("ltp"))
        if not sym or price<=0:continue
        cum=int(f(r.get("volume")));prev=previous_volume.get(sym,cum);delta=max(0,cum-prev);previous_volume[sym]=cum
        b=bars.get(sym)
        if not b:
            bars[sym]={"timestamp":ts.isoformat(),"date":ts.date().isoformat(),"minute":ts.strftime("%H:%M"),"symbol":sym,"security_id":r.get("security_id",""),"sector":r.get("sector",""),"open_1m":price,"high_1m":price,"low_1m":price,"close_1m":price,"volume_cumulative":cum,"volume_delta_1m":delta,"average_price":f(r.get("average_price")),"open_0915":f(r.get("open_0915",r.get("open"))),"previous_close":f(r.get("previous_close")),"from_open_pct":f(r.get("from_open_pct",r.get("move_from_open_percent"))),"day_high":f(r.get("day_high",r.get("high"))),"day_low":f(r.get("day_low",r.get("low"))),"range_position_pct":f(r.get("range_position_pct",r.get("range_position_percent"))),"direction":r.get("direction",""),"samples_in_minute":1}
        else:
            b["timestamp"]=ts.isoformat();b["high_1m"]=max(f(b["high_1m"]),price);b["low_1m"]=min(f(b["low_1m"]),price);b["close_1m"]=price;b["volume_cumulative"]=cum;b["volume_delta_1m"]=int(b.get("volume_delta_1m",0))+delta;b["average_price"]=f(r.get("average_price"));b["from_open_pct"]=f(r.get("from_open_pct",r.get("move_from_open_percent")));b["day_high"]=f(r.get("day_high",r.get("high")));b["day_low"]=f(r.get("day_low",r.get("low")));b["range_position_pct"]=f(r.get("range_position_pct",r.get("range_position_percent")));b["direction"]=r.get("direction","");b["samples_in_minute"]=int(b.get("samples_in_minute",0))+1

def main():
    print("="*96);print("APlus Breakout Evidence Collector V1");print("ZERO Dhan calls - local Market Watch only");print("="*96)
    try:
        while True:
            now=datetime.now(IST)
            if now.weekday()>=5:time.sleep(60);continue
            if now.time()>dtime(15,35):
                if current_minute:flush(current_minute)
                return
            cycle();time.sleep(5)
    finally:
        if current_minute:flush(current_minute)

if __name__=="__main__":main()
