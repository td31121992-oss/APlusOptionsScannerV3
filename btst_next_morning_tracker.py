from __future__ import annotations

import csv, json, math, time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

IST=ZoneInfo("Asia/Kolkata")
ROOT=Path(__file__).resolve().parent
REPORTS=ROOT/"data"/"reports"
STATE=ROOT/"data"/"research"/"btst"
MARKET_WATCH=REPORTS/"fno_market_watch_latest.json"

def num(v,d=0.0):
    try:
        x=float(v); return x if math.isfinite(x) else d
    except:return d

def load_json(p):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except:return {}

def previous_btst_file():
    days=sorted([p for p in STATE.iterdir() if p.is_dir()],reverse=True) if STATE.exists() else []
    for d in days:
        files=sorted(d.glob("btst_snapshot_*.json"))
        if files:return files[-1]
    return None

def main():
    src=previous_btst_file()
    if not src:
        raise SystemExit("No previous BTST candidate snapshot found.")
    previous=load_json(src)
    qualified=previous.get("qualified",[]) or []
    print("="*76)
    print("APlus BTST Next-Morning Tracker")
    print("Source:",src)
    print("Candidates:",len(qualified))
    print("PAPER / RESEARCH ONLY")
    print("="*76)

    out=REPORTS/"btst_next_morning_latest.json"
    until=dtime(10,0)

    while True:
        now=datetime.now(IST)
        if now.time()<dtime(9,15):
            time.sleep(10);continue
        mw=load_json(MARKET_WATCH)
        rows={str(x.get("symbol") or "").upper():x for x in mw.get("rows",[]) if isinstance(x,dict)}
        results=[]
        for c in qualified:
            sym=str(c.get("symbol") or "").upper()
            r=rows.get(sym)
            if not r:continue
            direction=c.get("direction")
            gap=num(r.get("gap_pct"))
            from_open=num(r.get("from_open_pct"))
            favorable_gap = gap if direction=="BULLISH" else -gap
            favorable_follow = from_open if direction=="BULLISH" else -from_open
            results.append({
                "source_trading_date": previous.get("trading_date"),
                "tracked_at": now.isoformat(),
                "symbol": sym,
                "sector": c.get("sector"),
                "direction": direction,
                "option_side": c.get("option_side"),
                "btst_score": c.get("score"),
                "next_day_gap_pct": gap,
                "next_day_from_open_pct": from_open,
                "favorable_gap_pct": round(favorable_gap,3),
                "favorable_followthrough_pct": round(favorable_follow,3),
                "gap_success": favorable_gap>0,
                "followthrough_success": favorable_follow>0,
            })
        payload={"generated_at":now.isoformat(),"source_snapshot":str(src),"results":results}
        out.write_text(json.dumps(payload,indent=2),encoding="utf-8")
        print(now.strftime("%H:%M:%S"),[(x["symbol"],x["favorable_gap_pct"],x["favorable_followthrough_pct"]) for x in results])
        if now.time()>=until:return
        time.sleep(60)

if __name__=="__main__":
    main()
