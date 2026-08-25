from __future__ import annotations
import argparse,csv,json,math,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
IST=ZoneInfo("Asia/Kolkata")
ROOT=Path(__file__).resolve().parent

TOP_DEFAULT=["MUTHOOTFIN","VMM","SIEMENS","GLENMARK","SAIL","CROMPTON","PREMIERENE","DIXON","SBILIFE","KAYNES"]

def num(v,d=0.0):
    try:return float(v)
    except:return d
def read_csv(p):
    try:
        with p.open("r",encoding="utf-8-sig",newline="") as h:return [dict(r) for r in csv.DictReader(h)]
    except:return []
def parse_log(p,symbol):
    if not p.exists():return []
    out=[]
    for line in p.read_text(encoding="utf-8",errors="ignore").splitlines():
        if symbol in line and ("LEADERSHIP_V6_SHADOW" in line or "PAPER conversion audit" in line or "OPTION_EXPIRY_FALLBACK" in line):
            out.append(line)
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--day",default=datetime.now(IST).date().isoformat());p.add_argument("--symbols",default=",".join(TOP_DEFAULT));a=p.parse_args()
    syms=[x.strip().upper() for x in a.symbols.split(",") if x.strip()]
    report=ROOT/"data"/"reports"; log=ROOT/"logs"/"scanner.log"
    state=ROOT/"data"/"intraday_movement"/a.day/"state.json"
    if not state.exists():
        # common location used by current build
        state=ROOT/"data"/"intraday_movement"/"state.json"
    obj={}
    try:obj=json.loads(state.read_text(encoding="utf-8"))
    except:pass
    paper=read_csv(report/"paper_trades.csv")
    fut=read_csv(report/"stock_futures_paper.csv")
    rows=[]
    for s in syms:
        st={}
        # probe several known state shapes
        for rootkey in ("symbols","symbol_states","states","runtime"):
            x=obj.get(rootkey,{}) if isinstance(obj,dict) else {}
            if isinstance(x,dict) and s in x:st=x[s];break
        trades=[t for t in paper if str(t.get("symbol") or "").upper()==s]
        ftr=[t for t in fut if str(t.get("symbol") or "").upper()==s]
        logs=parse_log(log,s)
        first_v6=""
        first_conv=""
        for line in logs:
            tm=line[:19]
            if "LEADERSHIP_V6_SHADOW" in line and not first_v6:first_v6=tm
            if "PAPER conversion audit" in line and not first_conv:first_conv=tm
        row={
            "symbol":s,
            "state_first_movement":st.get("first_movement_at") or st.get("first_seen_at") or "",
            "highest_trade_quality":st.get("highest_trade_quality_score") or st.get("highest_quality") or "",
            "first_v6_log":first_v6,
            "first_conversion_log":first_conv,
            "option_trades":len(trades),
            "option_pnl":round(sum(num(t.get("net_pnl")) for t in trades),2),
            "futures_paper_trades":len(ftr),
            "futures_pnl":round(sum(num(t.get("gross_pnl")) for t in ftr if t.get("status")=="CLOSED"),2),
            "last_conversion_evidence":next((x for x in reversed(logs) if "PAPER conversion audit" in x),""),
        }
        rows.append(row)
    print("="*120);print("APLUS V6.4 TOP-MOVER MISS FORENSIC -",a.day);print("="*120)
    for r in rows:
        print(f'{r["symbol"]:12} first={str(r["state_first_movement"]):20} V6={r["first_v6_log"]:19} optionTrades={r["option_trades"]} optionPnL={r["option_pnl"]:9.2f} futTrades={r["futures_paper_trades"]} futPnL={r["futures_pnl"]:9.2f}')
        if r["last_conversion_evidence"]:print("  ",r["last_conversion_evidence"][-220:])
    out=report/f"leadership_v6_4_forensic_{a.day}.csv"
    with out.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print("Saved:",out)
if __name__=="__main__":main()
