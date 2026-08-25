from __future__ import annotations
import argparse,csv,json
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

def normalized_chart(day):
    out={}
    p=ROOT/"data"/"chart_history"/day/"market_watch_1m.csv"
    for r in loadc(p):
        s=str(r.get("symbol") or "").upper();tm=str(r.get("minute") or "")
        if not s or not tm:continue
        px=f(r.get("ltp")); mv=f(r.get("from_open_pct"))
        out[(s,tm)]={"symbol":s,"time":tm,"price":px,"move":mv,"source":"chart_history"}
    return out

def normalized_breakout(day):
    out={}
    p=ROOT/"data"/"breakout_evidence"/day/"market_watch_1m_ohlcv.csv"
    for r in loadc(p):
        s=str(r.get("symbol") or "").upper();tm=str(r.get("minute") or "")
        if not s or not tm:continue
        px=f(r.get("close_1m"));mv=f(r.get("from_open_pct"))
        out[(s,tm)]={"symbol":s,"time":tm,"price":px,"move":mv,"source":"breakout_evidence"}
    return out

def main():
    a=argparse.ArgumentParser();a.add_argument("--day",default=datetime.now(IST).date().isoformat());x=a.parse_args();day=x.day
    merged=normalized_chart(day)
    # Prefer true OHLC-derived close where available, but keep earlier chart history.
    merged.update(normalized_breakout(day))
    by={}
    for r in merged.values():by.setdefault(r["symbol"],[]).append(r)
    for s in by:by[s].sort(key=lambda z:z["time"])

    res=[]
    for s,rr in by.items():
        if len(rr)<2:continue
        peak=max(z["move"] for z in rr); trough=min(z["move"] for z in rr)
        up=abs(peak)>=abs(trough);best=peak if up else trough
        start=""
        for i in range(5,len(rr)):
            p0,p1=rr[i-5]["price"],rr[i]["price"];m5=((p1-p0)/p0*100) if p0 else 0;mv=rr[i]["move"]
            if (up and mv>=.45 and m5>=.20) or ((not up) and mv<=-.45 and m5<=-.20):
                start=rr[i]["time"];break
        res.append({
            "symbol":s,"direction":"UP" if up else "DOWN","best_move_pct":best,
            "final_move_pct":rr[-1]["move"],"movement_start_time":start,
            "coverage_start":rr[0]["time"],"coverage_end":rr[-1]["time"],
            "minutes_available":len(rr)
        })

    focus=sorted([r for r in res if r["direction"]=="UP"],key=lambda z:z["best_move_pct"],reverse=True)[:5]+sorted([r for r in res if r["direction"]=="DOWN"],key=lambda z:z["best_move_pct"])[:5]
    obj=loadj(ROOT/"data"/"reports"/"paper_trades_latest.json");trs=[]
    if isinstance(obj,dict):
        for k in ("paper_trades","trades","rows"):
            if isinstance(obj.get(k),list):trs=obj[k];break
    elif isinstance(obj,list):trs=obj

    for r in focus:
        ts=[t for t in trs if str(t.get("symbol") or "").upper()==r["symbol"] and str(t.get("entry_time") or "")[:10]==day]
        t=min(ts,key=lambda z:str(z.get("entry_time") or "")) if ts else None
        r["trade_taken"]=bool(t)
        r["trade_entry_time"]=str(t.get("entry_time") or "")[11:16] if t else ""
        r["trade_pnl"]=f(t.get("net_pnl",t.get("pnl"))) if t else 0.0
        et=r["trade_entry_time"]
        rr=by.get(r["symbol"],[])
        entryrow=next((q for q in reversed(rr) if et and q["time"]<=et),None)
        r["move_at_trade_entry_pct"]=entryrow["move"] if entryrow else None
        if entryrow:
            r["move_completed_before_entry_pct"]=abs(entryrow["move"])
            r["remaining_best_move_after_entry_pct"]=max(0.0,abs(r["best_move_pct"])-abs(entryrow["move"]))
        else:
            r["move_completed_before_entry_pct"]=None
            r["remaining_best_move_after_entry_pct"]=None

    od=ROOT/"data"/"reports"/"movement_forensics_v2_3"/day;od.mkdir(parents=True,exist_ok=True)
    cp=od/"top_bottom_movement_forensic.csv"
    fields=list(focus[0].keys()) if focus else ["symbol"]
    with cp.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(focus)
    latest=ROOT/"data"/"reports"/"movement_forensics_v2_3_latest.json"
    latest.write_text(json.dumps({"day":day,"rows":focus,"csv":str(cp)},indent=2),encoding="utf-8")
    print("APlus Movement Forensics V2.3",day,"MERGED chart_history + breakout_evidence")
    for r in focus:print(r)
    print("CSV:",cp)

if __name__=="__main__":main()
