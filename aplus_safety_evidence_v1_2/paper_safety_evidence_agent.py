from __future__ import annotations
import json, time, os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
IST=ZoneInfo("Asia/Kolkata")
REPORT=ROOT/"data"/"reports"/"paper_trades_latest.json"
MOVEMENT=ROOT/"data"/"reports"/"intraday_movement_latest.json"
MARKET=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
STATE=ROOT/"data"/"portfolio_state.json"
CAPS=ROOT/"data"/"trade_evidence_capsules"

def load_json(p):
    try:return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:return {}

def rows(obj):
    if isinstance(obj,list): return [x for x in obj if isinstance(x,dict)]
    if isinstance(obj,dict):
        for k in ("paper_trades","trades","rows"):
            v=obj.get(k)
            if isinstance(v,list): return [x for x in v if isinstance(x,dict)]
    return []

def f(v,d=0.0):
    try:return float(v)
    except Exception:return d

def atom_write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,default=str),encoding="utf-8")
    os.replace(tmp,path)

def latest_map(obj):
    out={}
    if isinstance(obj,dict):
        cand=[]
        for k in ("candidates","entry_ready","analysed","rows","stocks","data"):
            v=obj.get(k)
            if isinstance(v,list): cand.extend(v)
    elif isinstance(obj,list): cand=obj
    else:cand=[]
    for r in cand:
        if isinstance(r,dict):
            s=str(r.get("symbol") or "").upper()
            if s: out[s]=r
    return out

def trade_day(trade):
    raw=str(trade.get("entry_time") or trade.get("signal_time") or "")
    return raw[:10] if len(raw)>=10 else datetime.now(IST).date().isoformat()

def compute_state(trades,today):
    todays=[t for t in trades if trade_day(t)==today]
    closed=[t for t in todays if str(t.get("status") or "").upper()=="CLOSED"]
    opened=[t for t in todays if str(t.get("status") or "").upper()=="OPEN"]
    realized=sum(f(t.get("net_pnl",t.get("pnl"))) for t in closed)
    streak=0
    for t in sorted(closed,key=lambda x:str(x.get("exit_time") or x.get("entry_time") or "")):
        pnl=f(t.get("net_pnl",t.get("pnl")))
        if pnl<0: streak+=1
        elif pnl>0: streak=0
    open_premium=sum(f(t.get("capital_required",t.get("total_premium",t.get("capital_used")))) for t in opened)
    open_risk=sum(f(t.get("total_risk",t.get("risk"))) for t in opened)
    return {
        "as_of":datetime.now(IST).isoformat(),
        "date":today,
        "mode":"PAPER_NATIVE",
        "trades_today":len(todays),
        "closed_trades_today":len(closed),
        "open_positions":len(opened),
        "realized_pnl_today":round(realized,2),
        "consecutive_losses":streak,
        "open_premium":round(open_premium,2),
        "open_total_risk":round(open_risk,2),
        "source":"paper_trades_latest.json",
    }

def capsule_for(t,market,movement):
    sym=str(t.get("symbol") or "").upper()
    m=market.get(sym,{})
    c=movement.get(sym,{})
    return {
        "captured_at":datetime.now(IST).isoformat(),
        "trade_id":t.get("trade_id",""),
        "symbol":sym,
        "direction":t.get("direction",t.get("side","")),
        "status":t.get("status",""),
        "entry_time":t.get("entry_time",t.get("signal_time","")),
        "exit_time":t.get("exit_time",""),
        "pnl":f(t.get("net_pnl",t.get("pnl"))),
        "exit_reason":t.get("exit_reason",""),
        "setup_family":t.get("setup_family",t.get("setup","")),
        "trade_quality_score":t.get("trade_quality_score",c.get("trade_quality_score")),
        "clean_trend_score":t.get("clean_trend_score",c.get("clean_trend_score")),
        "trend_alignment_score":t.get("trend_alignment_score",c.get("trend_alignment_score")),
        "underlying_snapshot":{
            "ltp":m.get("ltp",c.get("underlying_ltp")),
            "open_0915":m.get("open_0915",m.get("open")),
            "previous_close":m.get("previous_close"),
            "from_open_pct":m.get("from_open_pct",m.get("move_from_open_percent")),
            "day_high":m.get("day_high",m.get("high")),
            "day_low":m.get("day_low",m.get("low")),
            "range_position_pct":m.get("range_position_pct",m.get("range_position_percent")),
            "average_price":m.get("average_price"),
            "volume":m.get("volume"),
        },
        "scanner_snapshot":c,
        "trade_record":t,
    }

def one_cycle():
    obj=load_json(REPORT)
    trades=rows(obj)
    today=datetime.now(IST).date().isoformat()
    state=compute_state(trades,today)
    atom_write(STATE,state)

    market=latest_map(load_json(MARKET))
    movement=latest_map(load_json(MOVEMENT))
    for t in trades:
        tid=str(t.get("trade_id") or "").strip()
        if not tid: continue
        day=trade_day(t)
        p=CAPS/day/f"{tid}.json"
        # update capsule while trade is open and once more when closed
        cap=capsule_for(t,market,movement)
        atom_write(p,cap)

def main():
    print("="*92)
    print("APlus PAPER Safety + Evidence Agent V1.1")
    print("ZERO Dhan calls - reads local reports only")
    print("="*92)
    while True:
        one_cycle()
        time.sleep(5)

if __name__=="__main__":main()
