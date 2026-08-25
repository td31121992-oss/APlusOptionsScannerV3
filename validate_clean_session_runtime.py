from __future__ import annotations
import json,re,time,argparse
from datetime import datetime,time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent; IST=ZoneInfo("Asia/Kolkata")
LOG=ROOT/"logs"/"scanner.log"; STATE=ROOT/"data"/"portfolio_state.json"
STATUS=ROOT/"data"/"reports"/"paper_safety_evidence_status.json"
OUT=ROOT/"data"/"reports"/"clean_session_runtime_validation_latest.json"
RX=re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?entry_ready=(?P<e>\d+).*?plans=(?P<p>\d+).*?paper_today=(?P<t>\d+).*?safety_blocked=(?P<b>\d+)")
def load(p):
    try:return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except:return {}
def run():
    now=datetime.now(IST); day=now.date().isoformat(); lines=[]
    if LOG.exists(): lines=[x for x in LOG.read_text(encoding="utf-8",errors="ignore").splitlines() if day in x]
    cycles=[]; blocks=[x for x in lines if "PAPER_SAFETY_BLOCK" in x]
    for x in lines:
        m=RX.search(x)
        if m: cycles.append({"timestamp":m["ts"],"entry_ready":int(m["e"]),"plans":int(m["p"]),"paper_today":int(m["t"]),"safety_blocked":int(m["b"])})
    proof=next((c for c in reversed(cycles) if c["entry_ready"]>0 and c["safety_blocked"]>0),None)
    caps=ROOT/"data"/"trade_evidence_capsules"/day
    br=ROOT/"data"/"breakout_evidence"/day/"market_watch_1m_ohlcv.csv"
    r={"as_of":now.isoformat(),"date":day,"latest_cycle":cycles[-1] if cycles else None,"paper_safety_blocks":len(blocks),
       "runtime_circuit_breaker_proven":bool(proof and blocks),"proof_cycle":proof,"portfolio_state":load(STATE),
       "evidence_status":load(STATUS),"capsules_today":len(list(caps.glob("*.json"))) if caps.exists() else 0,
       "breakout_evidence_exists":br.exists()}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(r,indent=2),encoding="utf-8")
    print(json.dumps(r,indent=2)); return r
def main():
    a=argparse.ArgumentParser(); a.add_argument("--watch",action="store_true"); a.add_argument("--interval",type=int,default=60); x=a.parse_args()
    while True:
        run()
        if not x.watch or datetime.now(IST).time()>=dtime(15,36): break
        time.sleep(max(10,x.interval))
if __name__=="__main__": main()
