from __future__ import annotations
import csv, json, time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
REPORT=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
BASE=ROOT/"data"/"chart_history"
STATE=BASE/"collector_state.json"
IST=ZoneInfo("Asia/Kolkata")
FIELDS=["timestamp","date","minute","symbol","security_id","sector","ltp","open_0915","previous_close","gap_pct","from_open_pct","from_prev_close_pct","day_high","day_low","range_position_pct","direction"]

def load_state():
    try:return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except Exception:return {}

def save_state(s):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(s,indent=2),encoding="utf-8");tmp.replace(STATE)

def append_rows(ts,rows):
    day=ts.date().isoformat();daydir=BASE/day;daydir.mkdir(parents=True,exist_ok=True);p=daydir/"market_watch_1m.csv"
    exists=p.exists()
    with p.open("a",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore")
        if not exists:w.writeheader()
        for r in rows:
            x=dict(r);x["timestamp"]=ts.isoformat();x["date"]=day;x["minute"]=ts.strftime("%H:%M");w.writerow(x)

def one_cycle():
    if not REPORT.exists():return False
    try:d=json.loads(REPORT.read_text(encoding="utf-8"))
    except Exception:return False
    rows=d.get("rows",[]) if isinstance(d,dict) else []
    if not rows:return False
    try:ts=datetime.fromisoformat(str(d.get("generated_at") or "")).astimezone(IST)
    except Exception:ts=datetime.now(IST)
    key=ts.strftime("%Y-%m-%dT%H:%M");st=load_state()
    if st.get("last_minute")==key:return True
    append_rows(ts,rows);save_state({"last_minute":key,"updated_at":datetime.now(IST).isoformat(),"rows":len(rows)})
    return True

def main():
    print("="*78);print("APlus Stock Chart History Collector");print("ZERO Dhan API calls");print("="*78)
    while True:
        now=datetime.now(IST)
        if now.weekday()>=5:time.sleep(60);continue
        if now.time()>dtime(15,35):print("Session complete.");return
        one_cycle();time.sleep(5)

if __name__=="__main__":main()
