from __future__ import annotations

import argparse, csv, json, time
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

IST=ZoneInfo("Asia/Kolkata")
ROOT=Path(__file__).resolve().parent
REPORT=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
OUT=ROOT/"data"/"historical_backtest"

def load_universe():
    if not REPORT.is_file():
        raise SystemExit(f"Missing universe source: {REPORT}")
    obj=json.loads(REPORT.read_text(encoding="utf-8"))
    rows=obj.get("rows",[])
    out=[]
    seen=set()
    for r in rows:
        if not isinstance(r,dict): continue
        sym=str(r.get("symbol") or "").strip().upper()
        sid=str(r.get("security_id") or "").strip()
        if sym and sid and sid not in seen:
            seen.add(sid); out.append((sym,sid))
    if not out: raise SystemExit("No F&O symbols/security IDs found in market-watch report.")
    return out

def main():
    ap=argparse.ArgumentParser(description="READ-ONLY Dhan 5m historical downloader for APlus backtest")
    ap.add_argument("--days",type=int,default=30)
    ap.add_argument("--sleep",type=float,default=1.25,help="delay between symbols; protects Dhan rate limits")
    ap.add_argument("--limit",type=int,default=0,help="optional symbol limit for test")
    ap.add_argument("--force-market-hours",action="store_true")
    args=ap.parse_args()

    now=datetime.now(IST)
    if dtime(9,15) <= now.time() <= dtime(15,35) and not args.force_market_hours:
        print("="*80)
        print("SAFETY STOP: market is open.")
        print("Historical bulk download is intentionally blocked during 09:15-15:35 IST")
        print("so it cannot compete with the live APlus scanner for Dhan API capacity.")
        print("Run this after 15:35 today.")
        print("="*80)
        return 3

    from config import AppConfig
    from core.dhan_client import DhanClient

    cfg=AppConfig.from_env()
    client=DhanClient(cfg.dhan)
    universe=load_universe()
    if args.limit>0: universe=universe[:args.limit]

    to_dt=now
    from_dt=datetime.combine((now-timedelta(days=args.days)).date(),dtime(9,15),tzinfo=IST)
    OUT.mkdir(parents=True,exist_ok=True)
    fn=OUT/f"fno_5m_{from_dt:%Y%m%d}_{to_dt:%Y%m%d}.csv"
    fail=OUT/f"fno_5m_failures_{from_dt:%Y%m%d}_{to_dt:%Y%m%d}.json"

    fields=["symbol","security_id","timestamp","open","high","low","close","volume"]
    failures=[]
    written=0
    print("="*84)
    print("APLUS HISTORICAL 5M BACKTEST DATA DOWNLOAD - READ ONLY")
    print("Symbols:",len(universe),"Range:",from_dt.isoformat(),"->",to_dt.isoformat())
    print("Output:",fn)
    print("="*84)

    with fn.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for idx,(sym,sid) in enumerate(universe,1):
            try:
                resp=client.get_intraday_candles(
                    security_id=sid,segment="NSE_EQ",instrument="EQUITY",
                    interval=5,from_datetime=from_dt,to_datetime=to_dt,oi=False
                )
                ts=list(resp.get("timestamp",[]) or [])
                op=list(resp.get("open",[]) or [])
                hi=list(resp.get("high",[]) or [])
                lo=list(resp.get("low",[]) or [])
                cl=list(resp.get("close",[]) or [])
                vo=list(resp.get("volume",[]) or [])
                n=min(map(len,(ts,op,hi,lo,cl,vo))) if ts else 0
                for i in range(n):
                    t=ts[i]
                    try:
                        t=datetime.fromtimestamp(float(t),IST).isoformat()
                    except Exception:
                        t=str(t)
                    w.writerow({"symbol":sym,"security_id":sid,"timestamp":t,
                                "open":op[i],"high":hi[i],"low":lo[i],"close":cl[i],"volume":vo[i]})
                written+=n
                print(f"[{idx:03d}/{len(universe):03d}] {sym:<16} rows={n}")
            except Exception as e:
                failures.append({"symbol":sym,"security_id":sid,"error":f"{type(e).__name__}: {e}"})
                print(f"[{idx:03d}/{len(universe):03d}] {sym:<16} FAIL {type(e).__name__}: {e}")
            time.sleep(max(0.25,args.sleep))

    fail.write_text(json.dumps(failures,indent=2),encoding="utf-8")
    print("="*84)
    print("DOWNLOAD COMPLETE")
    print("Candle rows:",written)
    print("Symbols failed:",len(failures))
    print("CSV:",fn)
    print("Failures:",fail)
    print("="*84)
    return 0 if written else 2

if __name__=="__main__":
    raise SystemExit(main())
