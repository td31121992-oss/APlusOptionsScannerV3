from __future__ import annotations
import argparse,csv,json,math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent; IST=ZoneInfo("Asia/Kolkata")
def f(v,d=0.0):
    try:return float(v)
    except:return d
def loadj(p):
    try:return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except:return {}
def loadc(p):
    if not p.exists():return []
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def main():
    a=argparse.ArgumentParser();a.add_argument("--day",default=datetime.now(IST).date().isoformat());x=a.parse_args();day=x.day
    p=ROOT/"data"/"breakout_evidence"/day/"market_watch_1m_ohlcv.csv"; rows=loadc(p); source="breakout_evidence"
    if not rows:
        p=ROOT/"data"/"chart_history"/day/"market_watch_1m.csv"; rows=loadc(p); source="chart_history"
    by={}
    for r in rows:
        s=str(r.get("symbol") or "").upper()
        if not s:continue
        px=f(r.get("close_1m",r.get("ltp"))); mv=f(r.get("from_open_pct"))
        by.setdefault(s,[]).append({"time":r.get("minute",""),"price":px,"move":mv})
    for s in by:by[s].sort(key=lambda z:z["time"])
    res=[]
    for s,rr in by.items():
        peak=max(z["move"] for z in rr); trough=min(z["move"] for z in rr); up=abs(peak)>=abs(trough); best=peak if up else trough
        start=""
        for i in range(5,len(rr)):
            p0,p1=rr[i-5]["price"],rr[i]["price"]; m5=((p1-p0)/p0*100) if p0 else 0; mv=rr[i]["move"]
            if (up and mv>=.45 and m5>=.20) or ((not up) and mv<=-.45 and m5<=-.20):start=rr[i]["time"];break
        res.append({"symbol":s,"direction":"UP" if up else "DOWN","best_move_pct":best,"final_move_pct":rr[-1]["move"],"movement_start_time":start})
    focus=sorted([r for r in res if r["direction"]=="UP"],key=lambda z:z["best_move_pct"],reverse=True)[:5]+sorted([r for r in res if r["direction"]=="DOWN"],key=lambda z:z["best_move_pct"])[:5]
    obj=loadj(ROOT/"data"/"reports"/"paper_trades_latest.json"); trs=[]
    if isinstance(obj,dict):
        for k in ("paper_trades","trades","rows"):
            if isinstance(obj.get(k),list):trs=obj[k];break
    for r in focus:
        ts=[t for t in trs if str(t.get("symbol") or "").upper()==r["symbol"] and str(t.get("entry_time") or "")[:10]==day]
        t=ts[0] if ts else None;r["trade_taken"]=bool(t);r["trade_entry_time"]=str(t.get("entry_time") or "")[11:16] if t else "";r["trade_pnl"]=f(t.get("net_pnl",t.get("pnl"))) if t else 0
    od=ROOT/"data"/"reports"/"movement_forensics_v2_2"/day;od.mkdir(parents=True,exist_ok=True)
    cp=od/"top_bottom_movement_forensic.csv";fields=list(focus[0].keys()) if focus else ["symbol"]
    with cp.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(focus)
    (ROOT/"data"/"reports"/"movement_forensics_v2_2_latest.json").write_text(json.dumps({"day":day,"source":source,"rows":focus,"csv":str(cp)},indent=2),encoding="utf-8")
    print("APlus Movement Forensics V2.2",day,source)
    for r in focus:print(r)
    print("CSV:",cp)
if __name__=="__main__":main()
