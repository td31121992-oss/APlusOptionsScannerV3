
from __future__ import annotations
import csv,json,argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent;IST=ZoneInfo("Asia/Kolkata")
def f(v,d=0.0):
    try:return float(v)
    except:return d
def loadj(p):
    try:return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except:return {}
def loadc(p):
    if not p.exists():return []
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def tonly(v):
    s=str(v or "");return s[11:16] if "T" in s and len(s)>=16 else s[:5]
def trade_rows(day):
    obj=loadj(ROOT/"data"/"reports"/"paper_trades_latest.json");rr=[]
    if isinstance(obj,list):rr=obj
    elif isinstance(obj,dict):
        for k in ("paper_trades","trades","rows"):
            if isinstance(obj.get(k),list):rr=obj[k];break
    return [r for r in rr if str(r.get("entry_time") or "")[:10]==day]
def history(day):
    merged={}
    for p in [ROOT/"data"/"chart_history"/day/"market_watch_1m.csv",ROOT/"data"/"breakout_evidence"/day/"market_watch_1m_ohlcv.csv"]:
        for r in loadc(p):
            s=str(r.get("symbol") or "").upper();tm=str(r.get("minute") or "")
            if not s or not tm:continue
            merged[(s,tm)]={"symbol":s,"time":tm,"move":f(r.get("from_open_pct"))}
    by={}
    for r in merged.values():by.setdefault(r["symbol"],[]).append(r)
    for s in by:by[s].sort(key=lambda q:q["time"])
    return by
def main():
    a=argparse.ArgumentParser();a.add_argument("--day",default=datetime.now(IST).date().isoformat());x=a.parse_args();day=x.day
    by=history(day);out=[]
    for t in trade_rows(day):
        pnl=f(t.get("net_pnl",t.get("pnl")))
        if pnl>=0:continue
        s=str(t.get("symbol") or "").upper();rr=by.get(s,[]);et,xt=tonly(t.get("entry_time")),tonly(t.get("exit_time"))
        er=next((r for r in reversed(rr) if et and r["time"]<=et),None);xr=next((r for r in reversed(rr) if xt and r["time"]<=xt),None)
        direction=str(t.get("direction") or t.get("side") or "").upper();bull=("CE" in direction or "BULL" in direction or direction in {"BUY","UP"})
        after=[r for r in rr if not et or r["time"]>=et]
        if not after:continue
        best=max(after,key=lambda r:r["move"]) if bull else min(after,key=lambda r:r["move"])
        entry_move=er["move"] if er else 0;addfav=(best["move"]-entry_move) if bull else (entry_move-best["move"])
        option_entry=f(t.get("entry_price",t.get("option_entry_price")));option_stop=f(t.get("option_stop"));holding=f(t.get("holding_seconds"))
        stop_pct=((option_entry-option_stop)/option_entry*100) if option_entry and option_stop else 0
        flags=[]
        if addfav>=.50 and str(t.get("exit_reason") or "")=="OPTION_STOP_LOSS":flags.append("STOCK_RIGHT_OPTION_STOPPED")
        if holding and holding<=180 and str(t.get("exit_reason") or "")=="OPTION_STOP_LOSS":flags.append("VERY_FAST_OPTION_STOP")
        if stop_pct and stop_pct<=11:flags.append("TIGHT_10PCT_OPTION_STOP")
        if addfav<.20:flags.append("UNDERLYING_FAILED_AFTER_ENTRY")
        if abs(entry_move)>=1.5 and addfav<=.8:flags.append("LATE_OR_MOVE_CONSUMED")
        out.append({
            "trade_id":t.get("trade_id",""),"symbol":s,"direction":direction,"entry_time":et,"exit_time":xt,
            "exit_reason":t.get("exit_reason",""),"pnl":pnl,"holding_seconds":holding,
            "underlying_move_at_entry_pct":entry_move,"underlying_move_at_exit_pct":xr["move"] if xr else None,
            "underlying_best_after_entry_pct":best["move"],"underlying_additional_favorable_move_pct":addfav,
            "underlying_best_time":best["time"],"option_entry":option_entry,"option_stop":option_stop,
            "option_exit":f(t.get("exit_price")),"option_high_seen":f(t.get("highest_option_price")),
            "option_low_seen":f(t.get("lowest_option_price")),"option_stop_distance_pct":stop_pct,
            "mfe_amount":f(t.get("mfe_amount")),"mae_amount":f(t.get("mae_amount")),
            "forensic_flags":"|".join(flags) or "DEEP_REVIEW"
        })
    od=ROOT/"data"/"reports"/"correct_stock_losing_option_forensic_v1"/day;od.mkdir(parents=True,exist_ok=True)
    cp=od/"losing_option_forensic.csv";fields=list(out[0].keys()) if out else ["trade_id"]
    with cp.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(out)
    (od/"losing_option_forensic.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    print("="*120);print("CORRECT-STOCK / LOSING-OPTION FORENSIC V1",day)
    for r in sorted(out,key=lambda z:z["underlying_additional_favorable_move_pct"],reverse=True):
        print(f"{r['symbol']:14s} pnl={r['pnl']:9.2f} addFav={r['underlying_additional_favorable_move_pct']:+6.2f}% hold={r['holding_seconds']:5.0f}s flags={r['forensic_flags']}")
    print("CSV:",cp);print("="*120)
if __name__=="__main__":main()
