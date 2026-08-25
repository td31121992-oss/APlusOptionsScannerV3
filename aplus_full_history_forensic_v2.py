from __future__ import annotations

"""
APlus Full-History Forensic V2
READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES

Primary question:
For every losing option trade, was the UNDERLYING STOCK CALL actually correct?

The tool searches all discoverable saved APlus files (current data + backups)
for timestamped underlying stock prices/moves, reconstructs a per-symbol timeline,
and classifies each option trade independently of option premium.

It does NOT assume cheap premium caused a loss.
"""

import argparse
import csv
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "reports" / "full_history_forensic_v2"
OUT.mkdir(parents=True, exist_ok=True)

TRADE_NAMES = {
    "paper_trade_history.csv","paper_trades.csv","paper_trades_latest.json",
    "paper_trade_history.json","paper_trade_journal.json"
}

SKIP_DIR_WORDS = (
    "\\venv\\","/venv/","\\.git\\","/.git/","\\site-packages\\","/site-packages/",
    "\\__pycache__\\","/__pycache__/"
)

PRICE_KEYS = (
    "ltp","last_price","last","price","current_price","underlying_ltp",
    "spot","close","last_traded_price"
)
MOVE_KEYS = (
    "from_open_pct","move_from_open_pct","move_from_0915_open_pct",
    "move_from_0915_open_percent","directional_move_pct","move_pct","change_from_open_pct"
)
TIME_KEYS = (
    "timestamp","generated_at","time","datetime","updated_at","captured_at",
    "quote_time","scan_time"
)
SYMBOL_KEYS = ("symbol","trading_symbol","underlying_symbol","stock_symbol")

def num(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""): return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def parse_dt(v: Any) -> datetime | None:
    s = str(v or "").strip()
    if not s: return None
    try: return datetime.fromisoformat(s)
    except Exception: pass
    for fmt in ("%Y-%m-%d %H:%M:%S","%d-%b-%Y %H:%M:%S","%Y/%m/%d %H:%M:%S","%H:%M:%S"):
        try:
            x = datetime.strptime(s[:19], fmt)
            return x
        except Exception:
            pass
    return None

def norm_symbol(v: Any) -> str:
    return str(v or "").strip().upper()

def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as h:
            return [dict(r) for r in csv.DictReader(h)]
    except Exception:
        return []

def json_rows(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return [dict(x) for x in obj if isinstance(x, dict)]
    if not isinstance(obj, dict):
        return []
    out = []
    for key in ("rows","data","stocks","market_watch","candidates","quotes","items","paper_trades","trades","history"):
        v = obj.get(key)
        if isinstance(v, list):
            out.extend(dict(x) for x in v if isinstance(x, dict))
        elif isinstance(v, dict):
            for k, x in v.items():
                if isinstance(x, dict):
                    y = dict(x)
                    y.setdefault("symbol", k)
                    out.append(y)
    if not out:
        # Handle symbol->object maps.
        if obj and all(isinstance(v, dict) for v in obj.values()):
            for k,v in obj.items():
                y=dict(v); y.setdefault("symbol", k); out.append(y)
    return out

def read_json_rows(path: Path) -> list[dict[str, Any]]:
    try:
        obj=json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return json_rows(obj)

def discover_files(root: Path) -> list[Path]:
    found=[]
    seen=set()
    for p in root.rglob("*"):
        if not p.is_file(): continue
        low=str(p).lower()
        if any(w in low for w in SKIP_DIR_WORDS): continue
        if p.suffix.lower() not in {".csv",".json"}: continue
        key=str(p.resolve())
        if key not in seen:
            seen.add(key); found.append(p)
    return found

# ---------------- trades ----------------

def is_trade_file(p: Path) -> bool:
    n=p.name.lower()
    return n in TRADE_NAMES or (("paper_trade" in n or "paper_trades" in n) and p.suffix.lower() in {".csv",".json"})

def canonical_trade_id(r):
    for k in ("paper_trade_id","trade_id","id"):
        v=str(r.get(k) or "").strip()
        if v:return v
    return "|".join([
        norm_symbol(r.get("symbol")),
        str(r.get("direction") or ""),
        str(r.get("option_type") or r.get("side") or ""),
        str(r.get("strike") or ""),
        str(r.get("entry_time") or r.get("generated_at") or "")
    ])

def normalize_trade(r: dict[str,Any], source: Path) -> dict[str,Any]:
    plan=r.get("plan") if isinstance(r.get("plan"),dict) else {}
    option=plan.get("option_contract") if isinstance(plan.get("option_contract"),dict) else {}
    underlying=plan.get("underlying") if isinstance(plan.get("underlying"),dict) else {}
    def get(*ks):
        for k in ks:
            for src in (r,plan,option):
                if isinstance(src,dict) and src.get(k) not in (None,""): return src.get(k)
        return ""
    edt=parse_dt(get("entry_time","generated_at"))
    xdt=parse_dt(get("exit_time"))
    day=str(r.get("trading_date") or "")[:10] or (edt.date().isoformat() if edt else "")
    pnl=num(get("net_pnl","gross_pnl"))
    capital=num(get("capital_deployed","total_premium","capital"))
    ret=num(get("return_percent"))
    if ret==0 and capital and pnl: ret=pnl/capital*100
    return {
        "trade_id":canonical_trade_id(r),
        "source_file":str(source),
        "trading_date":day,
        "symbol":norm_symbol(get("symbol")),
        "direction":str(get("direction")).upper(),
        "option_type":str(get("option_type","side")).upper(),
        "strike":num(get("strike")),
        "expiry":str(get("expiry")),
        "entry_time":edt.isoformat() if edt else str(get("entry_time","generated_at")),
        "exit_time":xdt.isoformat() if xdt else str(get("exit_time")),
        "entry_price":num(get("entry_price","option_ltp")),
        "exit_price":num(get("exit_price")),
        "capital_deployed":capital,
        "net_pnl":pnl,
        "return_percent":ret,
        "status":str(get("status")).upper(),
        "exit_reason":str(get("exit_reason")).upper(),
        "stage":str(get("stage")).upper(),
        "setup_family":str(get("setup_family")).upper(),
        "trade_quality_score":num(get("trade_quality_score","momentum_score")),
        "clean_trend_score":num(get("clean_trend_score")),
        "trend_alignment_score":num(get("trend_alignment_score")),
        "session_rvol":num(get("session_rvol","relative_volume")),
        "vwap_distance_pct":num(get("vwap_distance_pct","vwap_distance_percent")),
        "underlying_entry_hint":num(underlying.get("entry")) if underlying else 0.0,
    }

def dedupe(rows):
    by={}
    for r in rows:
        tid=r["trade_id"]; old=by.get(tid)
        score=sum(bool(r.get(k)) for k in ("exit_time","exit_price","net_pnl","return_percent"))
        oldscore=sum(bool(old.get(k)) for k in ("exit_time","exit_price","net_pnl","return_percent")) if old else -1
        if old is None or score>oldscore: by[tid]=r
    return sorted(by.values(), key=lambda r:(r["trading_date"],r["entry_time"],r["trade_id"]))

# ---------------- timeline discovery ----------------

def infer_file_day(path: Path) -> str:
    m=re.search(r"(20\d{2}-\d{2}-\d{2})",str(path))
    if m:return m.group(1)
    m=re.search(r"(20\d{2})(\d{2})(\d{2})",str(path))
    if m:return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""

def infer_file_time(path: Path) -> str:
    for pat in (r"rank_(\d{4})", r"_(\d{4})\.", r"T(\d{2})(\d{2})"):
        m=re.search(pat,path.name)
        if m:
            if len(m.groups())==1:
                x=m.group(1); return f"{x[:2]}:{x[2:]}:00"
            return f"{m.group(1)}:{m.group(2)}:00"
    return ""

def row_symbol(r: dict[str,Any]) -> str:
    for k in SYMBOL_KEYS:
        if r.get(k) not in (None,""): return norm_symbol(r.get(k))
    return ""

def row_time(r: dict[str,Any], path: Path) -> datetime | None:
    for k in TIME_KEYS:
        if r.get(k) not in (None,""):
            dt=parse_dt(r.get(k))
            if dt:
                if dt.year==1900:
                    day=infer_file_day(path)
                    if day:
                        try:return datetime.fromisoformat(day+"T"+dt.time().isoformat())
                        except Exception:pass
                return dt
    day=infer_file_day(path); tm=infer_file_time(path)
    if day and tm:
        try:return datetime.fromisoformat(day+"T"+tm)
        except Exception:return None
    return None

def row_value(r: dict[str,Any]) -> tuple[str,float] | None:
    for k in PRICE_KEYS:
        if r.get(k) not in (None,""):
            x=num(r.get(k))
            if x>0:return ("PRICE",x)
    for k in MOVE_KEYS:
        if r.get(k) not in (None,""):
            return ("MOVE",num(r.get(k)))
    return None

def source_priority(path: Path) -> int:
    s=str(path).lower()
    if "quote_tape" in s:return 100
    if "market_watch" in s:return 90
    if "rank_history" in s:return 80
    if "movement" in s:return 70
    if "opening" in s:return 60
    return 20

def build_timelines(files: list[Path], trade_files:set[str]):
    # day -> symbol -> list of dict(ts,kind,value,source,priority)
    tl=defaultdict(lambda:defaultdict(list))
    source_stats=defaultdict(int)
    for p in files:
        if str(p) in trade_files: continue
        name=p.name.lower()
        # Avoid bulky irrelevant sources.
        if not any(word in name for word in (
            "rank","movement","market_watch","quote_tape","opening","leadership",
            "intraday","candidate","technical","top_bottom","snapshot"
        )):
            continue
        rows=read_csv_rows(p) if p.suffix.lower()==".csv" else read_json_rows(p)
        if not rows: continue
        pr=source_priority(p)
        for r in rows:
            s=row_symbol(r)
            dt=row_time(r,p)
            val=row_value(r)
            if not s or not dt or not val: continue
            kind,x=val
            day=dt.date().isoformat()
            tl[day][s].append({"ts":dt,"kind":kind,"value":x,"source":str(p),"priority":pr})
            source_stats[str(p)]+=1
    for day in tl:
        for s in tl[day]:
            # Prefer highest priority if duplicate minute.
            items=sorted(tl[day][s],key=lambda x:(x["ts"],-x["priority"]))
            ded=[];seen=set()
            for x in items:
                key=(x["ts"].replace(second=0,microsecond=0),x["kind"])
                if key in seen:continue
                seen.add(key);ded.append(x)
            tl[day][s]=ded
    return tl,source_stats

def closest_at_or_after(series,target,max_minutes=5):
    if not series or target is None:return None
    for x in series:
        if x["ts"]>=target:
            if (x["ts"]-target).total_seconds()<=max_minutes*60:return x
            return None
    return None

def closest_at_or_before(series,target,max_minutes=5):
    if not series or target is None:return None
    for x in reversed(series):
        if x["ts"]<=target:
            if (target-x["ts"]).total_seconds()<=max_minutes*60:return x
            return None
    return None

def point_near(series,target,max_minutes=5):
    a=closest_at_or_after(series,target,max_minutes)
    b=closest_at_or_before(series,target,max_minutes)
    if a and b:
        return a if abs((a["ts"]-target).total_seconds())<=abs((target-b["ts"]).total_seconds()) else b
    return a or b

def directional_change(direction,start,end):
    if start is None or end is None:return None
    # Same representation only.
    if start["kind"]!=end["kind"]:return None
    if start["kind"]=="PRICE":
        if start["value"]<=0:return None
        raw=(end["value"]-start["value"])/start["value"]*100
    else:
        raw=end["value"]-start["value"]
    return raw if direction=="BULLISH" else -raw

def max_excursion(direction,series,start_dt,end_dt,start_point):
    if not series or not start_point:return (None,None)
    vals=[]
    for x in series:
        if x["ts"]<start_dt or x["ts"]>end_dt:continue
        d=directional_change(direction,start_point,x)
        if d is not None:vals.append(d)
    if not vals:return (None,None)
    return (max(vals),min(vals))

# ---------------- classification ----------------

def classify_underlying(r):
    # Use movement after ENTRY first, not option price.
    f5=r.get("u_after_entry_5m_pct");f15=r.get("u_after_entry_15m_pct")
    f30=r.get("u_after_entry_30m_pct");f60=r.get("u_after_entry_60m_pct")
    mfe=r.get("u_mfe_to_60m_pct");mae=r.get("u_mae_to_60m_pct")
    vals=[x for x in (f5,f15,f30,f60,mfe) if isinstance(x,(int,float))]
    if not vals:return "NO_UNDERLYING_EVIDENCE"
    best=max(vals)
    early=[x for x in (f5,f15) if isinstance(x,(int,float))]
    early_best=max(early) if early else None

    if best>=0.75:
        if early_best is not None and early_best>=0.25:
            return "CORRECT_STOCK_STRONG_CONTINUATION"
        return "CORRECT_STOCK_BUT_LATE_CONTINUATION"
    if best>=0.30:
        return "CORRECT_STOCK_MODEST_MOVE"
    if isinstance(mae,(int,float)) and mae<=-0.50:
        return "WRONG_STOCK_OR_BAD_ENTRY"
    return "NO_CLEAR_EDGE"

def classify_trade(r):
    pnl=num(r["net_pnl"])
    uclass=r.get("underlying_class","NO_UNDERLYING_EVIDENCE")
    if pnl>0:
        if uclass.startswith("CORRECT_STOCK"):
            return "WIN_CORRECT_STOCK"
        return "WIN_OTHER"
    if pnl<0:
        if uclass=="CORRECT_STOCK_STRONG_CONTINUATION":
            return "LOSS_CORRECT_STOCK_OPTION_OR_EXIT_FAILED"
        if uclass=="CORRECT_STOCK_BUT_LATE_CONTINUATION":
            return "LOSS_CORRECT_STOCK_TIMING_OR_EXIT_FAILED"
        if uclass=="CORRECT_STOCK_MODEST_MOVE":
            return "LOSS_STOCK_RIGHT_BUT_MOVE_TOO_SMALL"
        if uclass=="WRONG_STOCK_OR_BAD_ENTRY":
            return "LOSS_BAD_STOCK_OR_ENTRY"
        if uclass=="NO_CLEAR_EDGE":
            return "LOSS_NO_CLEAR_UNDERLYING_EDGE"
        return "LOSS_NO_UNDERLYING_EVIDENCE"
    return "FLAT"

# ---------------- reports ----------------

def stats(rows):
    closed=[r for r in rows if r.get("exit_time") or num(r.get("net_pnl"))!=0]
    wins=[r for r in closed if num(r["net_pnl"])>0];loss=[r for r in closed if num(r["net_pnl"])<0]
    gp=sum(num(r["net_pnl"]) for r in wins);gl=-sum(num(r["net_pnl"]) for r in loss)
    return {
        "trades":len(closed),"wins":len(wins),"losses":len(loss),
        "win_rate_pct":round(len(wins)/len(closed)*100,2) if closed else 0,
        "net_pnl":round(gp-gl,2),
        "gross_profit":round(gp,2),"gross_loss":round(gl,2),
        "profit_factor":round(gp/gl,3) if gl else None,
        "expectancy":round((gp-gl)/len(closed),2) if closed else 0
    }

def grouped(rows,key):
    by=defaultdict(list)
    for r in rows:by[str(r.get(key) or "UNKNOWN")].append(r)
    return [{"group":k,**stats(v)} for k,v in sorted(by.items())]

def write_csv(path,rows):
    if not rows:
        path.write_text("",encoding="utf-8");return
    fields=[];seen=set()
    for r in rows:
        for k in r:
            if k not in seen:seen.add(k);fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)

def make_html(summary,classes,underlying,days,trades,path):
    def tbl(rows,cols):
        h="".join(f"<th>{c}</th>" for c in cols)
        b="".join("<tr>"+"".join(f"<td>{r.get(c,'')}</td>" for c in cols)+"</tr>" for r in rows)
        return f"<table><tr>{h}</tr>{b}</table>"
    focus=sorted([r for r in trades if num(r["net_pnl"])<0 and str(r.get("underlying_class","")).startswith("CORRECT_STOCK")],key=lambda r:num(r["net_pnl"]))[:50]
    cols=["trading_date","symbol","direction","entry_time","entry_price","net_pnl","return_percent","underlying_class","root_cause","u_after_entry_5m_pct","u_after_entry_15m_pct","u_after_entry_30m_pct","u_after_entry_60m_pct","u_mfe_to_60m_pct"]
    html=f"""<!doctype html><html><head><meta charset='utf-8'><title>APlus Forensic V2</title>
<style>body{{font-family:Segoe UI,Arial;background:#0b1020;color:#e8eef9;margin:24px}}table{{width:100%;border-collapse:collapse;background:#121a2d;margin-bottom:28px}}th,td{{border-bottom:1px solid #2b354c;padding:7px;font-size:12px;text-align:left}}th{{color:#91a2c0}}.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}.c{{background:#121a2d;padding:12px;border-radius:12px}}.v{{font-size:21px;font-weight:700}}</style></head><body>
<h1>APlus Full-History Forensic V2 — Stock Call vs Option Outcome</h1>
<div class='cards'>
<div class='c'>Trades<div class='v'>{summary['trades']}</div></div>
<div class='c'>Win Rate<div class='v'>{summary['win_rate_pct']}%</div></div>
<div class='c'>Net P&L<div class='v'>{summary['net_pnl']}</div></div>
<div class='c'>Underlying Coverage<div class='v'>{summary['underlying_coverage_pct']}%</div></div>
<div class='c'>Correct-stock losing trades<div class='v'>{summary['correct_stock_losing_trades']}</div></div>
<div class='c'>Bad-stock/entry losing trades<div class='v'>{summary['bad_stock_losing_trades']}</div></div>
</div>
<h2>Root Cause</h2>{tbl(classes,['group','trades','wins','losses','win_rate_pct','net_pnl','profit_factor'])}
<h2>Underlying Classification</h2>{tbl(underlying,['group','trades','wins','losses','net_pnl'])}
<h2>Daily</h2>{tbl(days,['group','trades','wins','losses','win_rate_pct','net_pnl'])}
<h2>Most Important: Losing Options Where Stock Call Was Correct</h2>{tbl(focus,cols)}
</body></html>"""
    path.write_text(html,encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=str(ROOT))
    args=ap.parse_args()
    root=Path(args.root).resolve()

    files=discover_files(root)
    trade_files=[p for p in files if is_trade_file(p)]
    raw=[]
    for p in trade_files:
        rows=read_csv_rows(p) if p.suffix.lower()==".csv" else read_json_rows(p)
        for x in rows:
            r=normalize_trade(x,p)
            if r["symbol"] and r["entry_time"]:raw.append(r)
    trades=dedupe(raw)

    timeline_files=[p for p in files if not is_trade_file(p)]
    timelines,source_stats=build_timelines(timeline_files,{str(p) for p in trade_files})

    covered=0
    for r in trades:
        day=r["trading_date"];sym=r["symbol"];series=timelines.get(day,{}).get(sym,[])
        edt=parse_dt(r["entry_time"]);xdt=parse_dt(r["exit_time"])
        if not edt or not series:
            r["underlying_class"]="NO_UNDERLYING_EVIDENCE";r["root_cause"]=classify_trade(r);continue

        start=point_near(series,edt,5)
        if not start:
            r["underlying_class"]="NO_UNDERLYING_EVIDENCE";r["root_cause"]=classify_trade(r);continue
        covered+=1
        r["underlying_source_kind"]=start["kind"]
        r["underlying_source_file"]=start["source"]
        r["underlying_entry_observed_value"]=start["value"]

        for mins in (1,3,5,10,15,30,60):
            p=point_near(series,edt+timedelta(minutes=mins),5)
            r[f"u_after_entry_{mins}m_pct"]=directional_change(r["direction"],start,p) if p else ""

        end60=edt+timedelta(minutes=60)
        mfe,mae=max_excursion(r["direction"],series,edt,end60,start)
        r["u_mfe_to_60m_pct"]=mfe if mfe is not None else ""
        r["u_mae_to_60m_pct"]=mae if mae is not None else ""

        if xdt:
            exitp=point_near(series,xdt,5)
            r["u_at_exit_pct"]=directional_change(r["direction"],start,exitp) if exitp else ""
            if exitp:
                for mins in (5,15,30,60):
                    q=point_near(series,xdt+timedelta(minutes=mins),5)
                    r[f"u_after_exit_{mins}m_pct"]=directional_change(r["direction"],exitp,q) if q else ""

        r["underlying_class"]=classify_underlying(r)
        r["root_cause"]=classify_trade(r)

    closed=[r for r in trades if r.get("exit_time") or num(r["net_pnl"])!=0]
    summary=stats(trades)
    summary["underlying_coverage_pct"]=round(covered/len(closed)*100,2) if closed else 0
    summary["correct_stock_losing_trades"]=sum(1 for r in closed if num(r["net_pnl"])<0 and str(r.get("underlying_class","")).startswith("CORRECT_STOCK"))
    summary["bad_stock_losing_trades"]=sum(1 for r in closed if num(r["net_pnl"])<0 and r.get("underlying_class")=="WRONG_STOCK_OR_BAD_ENTRY")
    summary["no_underlying_evidence_losing_trades"]=sum(1 for r in closed if num(r["net_pnl"])<0 and r.get("underlying_class")=="NO_UNDERLYING_EVIDENCE")
    summary["first_day"]=min((r["trading_date"] for r in closed if r["trading_date"]),default="")
    summary["last_day"]=max((r["trading_date"] for r in closed if r["trading_date"]),default="")
    summary["unique_days"]=len(set(r["trading_date"] for r in closed if r["trading_date"]))
    summary["timeline_source_files"]=len(source_stats)
    summary["trade_source_files"]=len(trade_files)
    summary["read_only"]=True
    summary["dhan_calls"]=False
    summary["strategy_changes"]=False

    rootcause=grouped(closed,"root_cause")
    uclass=grouped(closed,"underlying_class")
    days=grouped(closed,"trading_date")
    setups=grouped(closed,"setup_family")

    write_csv(OUT/"all_trades_stock_vs_option.csv",trades)
    write_csv(OUT/"root_cause_summary.csv",rootcause)
    write_csv(OUT/"underlying_class_summary.csv",uclass)
    write_csv(OUT/"daily_summary.csv",days)
    write_csv(OUT/"setup_summary.csv",setups)
    write_csv(OUT/"timeline_sources.csv",[{"file":k,"points":v} for k,v in sorted(source_stats.items(),key=lambda x:x[1],reverse=True)])
    (OUT/"overall_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    make_html(summary,rootcause,uclass,days,trades,OUT/"stock_vs_option_forensic.html")

    print("="*126)
    print("APLUS FULL-HISTORY FORENSIC V2 — STOCK CALL vs OPTION OUTCOME")
    print("READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES")
    print("="*126)
    for k,v in summary.items():print(f"{k:40}: {v}")
    print()
    print("UNDERLYING CLASSIFICATION")
    for x in uclass:
        print(f'{x["group"]:42} trades={x["trades"]:3} wins={x["wins"]:3} losses={x["losses"]:3} pnl={x["net_pnl"]:11.2f}')
    print()
    print("ROOT CAUSE")
    for x in rootcause:
        print(f'{x["group"]:48} trades={x["trades"]:3} pnl={x["net_pnl"]:11.2f}')
    print()
    print("MOST IMPORTANT FILES")
    print(" ",OUT/"stock_vs_option_forensic.html")
    print(" ",OUT/"all_trades_stock_vs_option.csv")
    print(" ",OUT/"root_cause_summary.csv")
    print(" ",OUT/"timeline_sources.csv")
    print("="*126)

if __name__=="__main__":
    main()
