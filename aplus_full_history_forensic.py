from __future__ import annotations

"""
APlus Full-History Profitability + Trade Forensic V1
READ ONLY / RESEARCH ONLY / ZERO DHAN CALLS / ZERO STRATEGY CHANGES

Purpose:
- Collect every discoverable APlus paper trade from current reports and backups.
- De-duplicate by paper_trade_id/trade_id.
- Compare winners vs losers from the first available paper-trade day.
- Reconstruct underlying continuation after entry/exit when saved minute/rank history exists.
- Classify WHY trades won/lost using evidence, not hindsight guesses.
- Produce overall, daily, setup, time, premium, quality, and exit-reason summaries.
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
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"
OUT = REPORTS / "full_history_forensic"
OUT.mkdir(parents=True, exist_ok=True)

TRADE_FILE_PATTERNS = (
    "paper_trade_history.csv",
    "paper_trades.csv",
    "paper_trades_latest.json",
    "paper_trade_history.json",
    "paper_trade_journal.json",
)

def num(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def parse_dt(v: Any) -> datetime | None:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except Exception:
            pass
    return None

def norm_symbol(v: Any) -> str:
    return str(v or "").strip().upper()

def read_csv_file(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as h:
            return [dict(r) for r in csv.DictReader(h)]
    except Exception:
        return []

def read_json_file(path: Path) -> list[dict[str, Any]]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(obj, list):
        return [dict(x) for x in obj if isinstance(x, dict)]
    if not isinstance(obj, dict):
        return []
    for k in ("paper_trades", "trades", "history", "rows"):
        v = obj.get(k)
        if isinstance(v, list):
            return [dict(x) for x in v if isinstance(x, dict)]
    return []

def discover_trade_files(root: Path) -> list[Path]:
    found = []
    seen = set()
    # Current project + backups. Avoid venv/site-packages.
    for base in [root / "data", root]:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            low = str(p).lower()
            if any(x in low for x in ("\\venv\\", "/venv/", "\\.git\\", "/.git/", "\\site-packages\\", "/site-packages/")):
                continue
            name = p.name.lower()
            if name in {x.lower() for x in TRADE_FILE_PATTERNS} or (
                ("paper_trade" in name or "paper_trades" in name) and p.suffix.lower() in {".csv", ".json"}
            ):
                key = str(p.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(p)
    return sorted(found)

def canonical_trade_id(r: dict[str, Any]) -> str:
    for k in ("paper_trade_id", "trade_id", "id"):
        v = str(r.get(k) or "").strip()
        if v:
            return v
    return "|".join([
        norm_symbol(r.get("symbol")),
        str(r.get("direction") or ""),
        str(r.get("option_type") or r.get("side") or ""),
        str(r.get("strike") or ""),
        str(r.get("entry_time") or r.get("generated_at") or ""),
    ])

def trade_day(r: dict[str, Any]) -> str:
    v = str(r.get("trading_date") or "").strip()
    if v:
        return v[:10]
    dt = parse_dt(r.get("entry_time") or r.get("generated_at"))
    return dt.date().isoformat() if dt else ""

def normalize_trade(r: dict[str, Any], source: Path) -> dict[str, Any]:
    plan = r.get("plan") if isinstance(r.get("plan"), dict) else {}
    option = plan.get("option_contract") if isinstance(plan.get("option_contract"), dict) else {}
    underlying = plan.get("underlying") if isinstance(plan.get("underlying"), dict) else {}

    def get(*keys, default=""):
        for k in keys:
            if k in r and r.get(k) not in (None, ""):
                return r.get(k)
            if k in plan and plan.get(k) not in (None, ""):
                return plan.get(k)
            if k in option and option.get(k) not in (None, ""):
                return option.get(k)
        return default

    entry = num(get("entry_price", "option_ltp", default=0))
    exitp = num(get("exit_price", default=0))
    pnl = num(get("net_pnl", "gross_pnl", default=0))
    ret = num(get("return_percent", default=0))
    capital = num(get("capital_deployed", "total_premium", "capital", default=0))
    if not ret and capital and pnl:
        ret = pnl / capital * 100.0

    entry_dt = parse_dt(get("entry_time", "generated_at"))
    exit_dt = parse_dt(get("exit_time"))
    duration = (exit_dt - entry_dt).total_seconds() if entry_dt and exit_dt else num(get("holding_seconds", default=0))

    d = {
        "trade_id": canonical_trade_id(r),
        "source_file": str(source),
        "trading_date": trade_day(r),
        "symbol": norm_symbol(get("symbol")),
        "direction": str(get("direction")).upper(),
        "option_type": str(get("option_type", "side")).upper(),
        "strike": num(get("strike")),
        "expiry": str(get("expiry")),
        "entry_time": entry_dt.isoformat() if entry_dt else str(get("entry_time", "generated_at")),
        "exit_time": exit_dt.isoformat() if exit_dt else str(get("exit_time")),
        "entry_price": entry,
        "exit_price": exitp,
        "capital_deployed": capital,
        "planned_risk_percent": num(get("planned_risk_percent", default=0)),
        "net_pnl": pnl,
        "return_percent": ret,
        "duration_seconds": duration,
        "status": str(get("status", "result")).upper(),
        "exit_reason": str(get("exit_reason")).upper(),
        "stage": str(get("stage")).upper(),
        "setup_family": str(get("setup_family")).upper(),
        "selection_tier": str(get("selection_tier")).upper(),
        "pivot_state": str(get("pivot_state")).upper(),
        "trade_quality_score": num(get("trade_quality_score", "momentum_score")),
        "movement_capture_score": num(get("movement_capture_score")),
        "trend_alignment_score": num(get("trend_alignment_score")),
        "clean_trend_score": num(get("clean_trend_score")),
        "chase_risk_score": num(get("chase_risk_score")),
        "move_from_0915_open_pct": num(get("move_from_0915_open_pct", "move_from_0915_open_percent")),
        "recent_move_5m_pct": num(get("recent_move_5m_pct", "recent_move_5m_percent")),
        "recent_move_10m_pct": num(get("recent_move_10m_pct", "recent_move_10m_percent")),
        "recent_move_15m_pct": num(get("recent_move_15m_pct", "recent_move_15m_percent")),
        "recent_move_30m_pct": num(get("recent_move_30m_pct", "recent_move_30m_percent")),
        "session_rvol": num(get("session_rvol", "relative_volume")),
        "recent_15m_rvol": num(get("recent_15m_rvol")),
        "tape_accel_5m": num(get("tape_accel_5m")),
        "tape_accel_15m": num(get("tape_accel_15m")),
        "vwap_distance_pct": num(get("vwap_distance_pct", "vwap_distance_percent")),
        "adx": num(get("adx")),
        "rsi": num(get("rsi")),
        "mfe_amount": num(get("mfe_amount")),
        "mae_amount": num(get("mae_amount")),
        "underlying_entry": num(underlying.get("entry")) if underlying else 0,
        "underlying_stop": num(underlying.get("stop_loss")) if underlying else 0,
        "entry_reason_full": str(get("entry_reason", "entry_reason_full")),
    }
    return d

def dedupe_trades(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by = {}
    for r in rows:
        tid = r["trade_id"]
        old = by.get(tid)
        if old is None:
            by[tid] = r
            continue
        # Prefer the record with more completed information.
        score = sum(bool(r.get(k)) for k in ("exit_time","exit_price","net_pnl","return_percent","entry_reason_full"))
        oldscore = sum(bool(old.get(k)) for k in ("exit_time","exit_price","net_pnl","return_percent","entry_reason_full"))
        if score > oldscore:
            by[tid] = r
    return sorted(by.values(), key=lambda r: (r["trading_date"], r["entry_time"], r["trade_id"]))

# ---------- saved underlying history ----------

def discover_rank_history(root: Path) -> dict[str, list[Path]]:
    days = defaultdict(list)
    base = root / "data" / "time_relative_rank_history"
    if base.exists():
        for p in base.rglob("rank_*.csv"):
            m = re.search(r"(20\d{2}-\d{2}-\d{2})", str(p))
            if m:
                days[m.group(1)].append(p)
    return days

def build_underlying_timeline(paths: list[Path]) -> dict[str, list[tuple[datetime, float]]]:
    out = defaultdict(list)
    for p in sorted(paths):
        rows = read_csv_file(p)
        stamp = None
        m = re.search(r"rank_(\d{4})", p.stem)
        if m:
            hhmm = m.group(1)
            daym = re.search(r"(20\d{2}-\d{2}-\d{2})", str(p))
            if daym:
                try:
                    stamp = datetime.fromisoformat(f"{daym.group(1)}T{hhmm[:2]}:{hhmm[2:]}:00")
                except Exception:
                    pass
        for r in rows:
            sym = norm_symbol(r.get("symbol"))
            if not sym:
                continue
            ts = parse_dt(r.get("timestamp") or r.get("generated_at")) or stamp
            if not ts:
                continue
            # directional raw underlying movement from session open
            mv = None
            for k in ("move_pct","from_open_pct","move_from_open_pct","move_from_0915_open_pct","directional_move_pct"):
                if r.get(k) not in (None, ""):
                    mv = num(r.get(k))
                    break
            if mv is None:
                continue
            out[sym].append((ts, mv))
    for s in out:
        out[s].sort(key=lambda x:x[0])
    return out

def nearest_after(series, target: datetime, tolerance_min=3):
    if not series or not target:
        return None
    best = None
    for ts, mv in series:
        delta = (ts - target).total_seconds()
        if delta >= 0:
            best = (ts, mv, delta)
            break
    if best and best[2] <= tolerance_min*60:
        return best[1]
    return None

def infer_directional_delta(direction: str, start_move: float | None, end_move: float | None) -> float | None:
    if start_move is None or end_move is None:
        return None
    raw = end_move - start_move
    return raw if direction == "BULLISH" else -raw

def enrich_underlying(trades, rank_days):
    cache = {}
    for r in trades:
        day = r["trading_date"]
        if day not in rank_days:
            continue
        if day not in cache:
            cache[day] = build_underlying_timeline(rank_days[day])
        series = cache[day].get(r["symbol"], [])
        entry_dt = parse_dt(r["entry_time"])
        exit_dt = parse_dt(r["exit_time"])
        if not entry_dt:
            continue
        entry_move = nearest_after(series, entry_dt, 5)
        r["underlying_move_at_entry_pct"] = entry_move if entry_move is not None else ""
        if exit_dt:
            exit_move = nearest_after(series, exit_dt, 5)
            r["underlying_move_at_exit_pct"] = exit_move if exit_move is not None else ""
            r["underlying_directional_during_trade_pct"] = (
                infer_directional_delta(r["direction"], entry_move, exit_move)
                if entry_move is not None and exit_move is not None else ""
            )
            for mins in (5,15,30,60):
                later = nearest_after(series, exit_dt + timedelta(minutes=mins), 5)
                r[f"underlying_directional_after_exit_{mins}m_pct"] = (
                    infer_directional_delta(r["direction"], exit_move, later)
                    if exit_move is not None and later is not None else ""
                )
        for mins in (5,15,30,60):
            later = nearest_after(series, entry_dt + timedelta(minutes=mins), 5)
            r[f"underlying_directional_after_entry_{mins}m_pct"] = (
                infer_directional_delta(r["direction"], entry_move, later)
                if entry_move is not None and later is not None else ""
            )
    return trades

# ---------- forensic classification ----------

def premium_band(p):
    p=num(p)
    if p <= 0:return "UNKNOWN"
    if p < 15:return "<15"
    if p < 30:return "15-30"
    if p < 60:return "30-60"
    if p < 100:return "60-100"
    if p < 200:return "100-200"
    return ">=200"

def time_bucket(dtstr):
    dt=parse_dt(dtstr)
    if not dt:return "UNKNOWN"
    hm=dt.hour*60+dt.minute
    if hm < 9*60+30:return "09:15-09:29"
    if hm < 10*60:return "09:30-09:59"
    if hm < 11*60:return "10:00-10:59"
    if hm < 12*60:return "11:00-11:59"
    if hm < 13*60:return "12:00-12:59"
    if hm < 14*60:return "13:00-13:59"
    if hm < 15*60:return "14:00-14:59"
    return "15:00+"

def classify(r):
    pnl=num(r["net_pnl"]); ret=num(r["return_percent"])
    r["result_class"]="WIN" if pnl>0 else ("LOSS" if pnl<0 else "FLAT")
    r["premium_band"]=premium_band(r["entry_price"])
    r["entry_time_bucket"]=time_bucket(r["entry_time"])

    after5 = r.get("underlying_directional_after_exit_5m_pct")
    after15 = r.get("underlying_directional_after_exit_15m_pct")
    after30 = r.get("underlying_directional_after_exit_30m_pct")
    during = r.get("underlying_directional_during_trade_pct")

    evidence = []
    cause = ""

    if pnl > 0:
        if str(r.get("exit_reason")) in {"RUNNER_TRAIL_EXIT","OPTION_TARGET1","OPTION_TARGET2","OPTION_TARGET3","PROFIT_TRAIL"}:
            cause="WINNER_TREND_CAPTURE"
        elif str(r.get("exit_reason"))=="SESSION_END":
            cause="WINNER_HELD_TO_SESSION_END"
        else:
            cause="WINNER_OTHER"
    elif pnl < 0:
        postvals=[x for x in (after5,after15,after30) if isinstance(x,(int,float))]
        strong_post=max(postvals) if postvals else None
        if r["entry_price"]>0 and r["entry_price"]<=15 and str(r["exit_reason"])=="OPTION_STOP_LOSS":
            evidence.append("CHEAP_PREMIUM")
        if str(r["exit_reason"])=="OPTION_STOP_LOSS":
            evidence.append("OPTION_STOP_LOSS")
        if isinstance(during,(int,float)):
            evidence.append(f"UNDERLYING_DURING={during:+.3f}%")
        if strong_post is not None:
            evidence.append(f"BEST_POST_EXIT_30M={strong_post:+.3f}%")

        if strong_post is not None and strong_post >= 0.35 and str(r["exit_reason"])=="OPTION_STOP_LOSS":
            cause="FALSE_OPTION_STOP_UNDERLYING_CONTINUED"
        elif isinstance(during,(int,float)) and during <= -0.25:
            cause="BAD_OR_FAILED_UNDERLYING_SIGNAL"
        elif r["entry_price"]>0 and r["entry_price"]<=15:
            cause="OPTION_PREMIUM_FRAGILITY"
        elif num(r["chase_risk_score"])>=35:
            cause="CHASE_OR_LATE_ENTRY"
        else:
            cause="LOSS_NEEDS_DEEP_REVIEW"
    else:
        cause="FLAT"
    r["forensic_cause"]=cause
    r["forensic_evidence"]=" | ".join(evidence)
    return r

# ---------- reporting ----------

def stats(rows):
    closed=[r for r in rows if num(r["net_pnl"])!=0 or r["exit_time"]]
    wins=[r for r in closed if num(r["net_pnl"])>0]
    losses=[r for r in closed if num(r["net_pnl"])<0]
    gp=sum(num(r["net_pnl"]) for r in wins)
    gl=-sum(num(r["net_pnl"]) for r in losses)
    avgw=mean([num(r["net_pnl"]) for r in wins]) if wins else 0
    avgl=mean([abs(num(r["net_pnl"])) for r in losses]) if losses else 0
    expectancy=(gp-gl)/len(closed) if closed else 0
    return {
        "trades":len(closed),"wins":len(wins),"losses":len(losses),
        "win_rate_pct":round(len(wins)/len(closed)*100,2) if closed else 0,
        "net_pnl":round(gp-gl,2),"gross_profit":round(gp,2),"gross_loss":round(gl,2),
        "profit_factor":round(gp/gl,3) if gl else None,
        "avg_win":round(avgw,2),"avg_loss":round(avgl,2),
        "expectancy_per_trade":round(expectancy,2),
        "avg_return_pct":round(mean([num(r["return_percent"]) for r in closed]),3) if closed else 0,
    }

def grouped(rows,key):
    by=defaultdict(list)
    for r in rows:by[str(r.get(key) or "UNKNOWN")].append(r)
    return [{"group":k,**stats(v)} for k,v in sorted(by.items())]

def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:
        path.write_text("",encoding="utf-8");return
    fields=[]
    seen=set()
    for r in rows:
        for k in r:
            if k not in seen:seen.add(k);fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)

def html_report(summary, daily, causes, setup, premium, timeg, trades, coverage, path):
    def table(rows,cols):
        head="".join(f"<th>{c}</th>" for c in cols)
        body="".join("<tr>"+"".join(f"<td>{r.get(c,'')}</td>" for c in cols)+"</tr>" for r in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    worst=sorted([r for r in trades if num(r["net_pnl"])<0],key=lambda r:num(r["net_pnl"]))[:30]
    best=sorted([r for r in trades if num(r["net_pnl"])>0],key=lambda r:num(r["net_pnl"]),reverse=True)[:30]
    cols=["trading_date","symbol","direction","option_type","entry_time","entry_price","exit_price","net_pnl","return_percent","forensic_cause"]
    html=f"""<!doctype html><html><head><meta charset="utf-8"><title>APlus Full History Forensic</title>
<style>body{{font-family:Segoe UI,Arial;background:#0b1020;color:#e6edf7;margin:25px}}h1,h2{{color:#fff}}.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}.c{{background:#121a2d;padding:14px;border-radius:12px}}.v{{font-size:22px;font-weight:700}}table{{border-collapse:collapse;width:100%;background:#121a2d;margin:12px 0 28px}}th,td{{padding:7px;border-bottom:1px solid #28334a;font-size:12px;text-align:left}}th{{color:#8ea0bd}}.neg{{color:#ff4d6d}}.pos{{color:#35d07f}}</style></head><body>
<h1>APlus Full-History Profitability + Trade Forensic</h1>
<p>READ ONLY. ZERO DHAN CALLS. Evidence coverage for underlying continuation: {coverage}% of closed trades.</p>
<div class="cards">
<div class="c"><div>Trades</div><div class="v">{summary['trades']}</div></div>
<div class="c"><div>Win Rate</div><div class="v">{summary['win_rate_pct']}%</div></div>
<div class="c"><div>Net P&L</div><div class="v">{summary['net_pnl']}</div></div>
<div class="c"><div>Profit Factor</div><div class="v">{summary['profit_factor']}</div></div>
<div class="c"><div>Avg Win</div><div class="v">{summary['avg_win']}</div></div>
<div class="c"><div>Avg Loss</div><div class="v">{summary['avg_loss']}</div></div>
</div>
<h2>Daily</h2>{table(daily,['group','trades','wins','losses','win_rate_pct','net_pnl','profit_factor','expectancy_per_trade'])}
<h2>Forensic Causes</h2>{table(causes,['group','trades','wins','losses','win_rate_pct','net_pnl','profit_factor','expectancy_per_trade'])}
<h2>Setup Family</h2>{table(setup,['group','trades','win_rate_pct','net_pnl','profit_factor','expectancy_per_trade'])}
<h2>Premium Band</h2>{table(premium,['group','trades','win_rate_pct','net_pnl','profit_factor','expectancy_per_trade'])}
<h2>Entry Time Bucket</h2>{table(timeg,['group','trades','win_rate_pct','net_pnl','profit_factor','expectancy_per_trade'])}
<h2>Top Winners</h2>{table(best,cols)}
<h2>Worst Losers</h2>{table(worst,cols)}
</body></html>"""
    path.write_text(html,encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=str(ROOT))
    args=ap.parse_args()
    root=Path(args.root).resolve()

    files=discover_trade_files(root)
    raw=[]
    source_counts=[]
    for p in files:
        rows=read_csv_file(p) if p.suffix.lower()==".csv" else read_json_file(p)
        source_counts.append({"file":str(p),"rows":len(rows)})
        for r in rows:
            nr=normalize_trade(r,p)
            if nr["symbol"] and nr["entry_time"]:
                raw.append(nr)

    trades=dedupe_trades(raw)
    rank_days=discover_rank_history(root)
    trades=enrich_underlying(trades,rank_days)
    trades=[classify(r) for r in trades]

    closed=[r for r in trades if r["exit_time"] or num(r["net_pnl"])!=0]
    summary=stats(trades)
    daily=grouped(closed,"trading_date")
    causes=grouped(closed,"forensic_cause")
    setup=grouped(closed,"setup_family")
    premium=grouped(closed,"premium_band")
    timeg=grouped(closed,"entry_time_bucket")
    exitg=grouped(closed,"exit_reason")
    quality=grouped(closed,"result_class")

    evidence_closed=sum(1 for r in closed if isinstance(r.get("underlying_directional_after_entry_15m_pct"),(int,float)))
    coverage=round(evidence_closed/len(closed)*100,2) if closed else 0

    write_csv(OUT/"all_trades_forensic.csv",trades)
    write_csv(OUT/"daily_summary.csv",daily)
    write_csv(OUT/"forensic_cause_summary.csv",causes)
    write_csv(OUT/"setup_summary.csv",setup)
    write_csv(OUT/"premium_band_summary.csv",premium)
    write_csv(OUT/"entry_time_summary.csv",timeg)
    write_csv(OUT/"exit_reason_summary.csv",exitg)
    write_csv(OUT/"source_files.csv",source_counts)

    overall={
        **summary,
        "first_trade_day":min((r["trading_date"] for r in closed if r["trading_date"]),default=""),
        "last_trade_day":max((r["trading_date"] for r in closed if r["trading_date"]),default=""),
        "unique_trade_days":len(set(r["trading_date"] for r in closed if r["trading_date"])),
        "underlying_evidence_coverage_pct":coverage,
        "trade_source_files":len(files),
        "rank_history_days":len(rank_days),
        "read_only":True,
        "dhan_calls":False,
        "strategy_changes":False,
    }
    (OUT/"overall_summary.json").write_text(json.dumps(overall,indent=2),encoding="utf-8")
    html_report(overall,daily,causes,setup,premium,timeg,trades,coverage,OUT/"full_history_forensic.html")

    print("="*120)
    print("APLUS FULL-HISTORY PROFITABILITY + TRADE FORENSIC V1")
    print("READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES")
    print("="*120)
    for k,v in overall.items():print(f"{k:36}: {v}")
    print()
    print("FORENSIC CAUSES")
    for r in sorted(causes,key=lambda x:x["net_pnl"]):
        print(f'{r["group"]:42} trades={r["trades"]:3} win={r["win_rate_pct"]:6.2f}% pnl={r["net_pnl"]:10.2f} PF={r["profit_factor"]}')
    print()
    print("PREMIUM BANDS")
    for r in premium:
        print(f'{r["group"]:10} trades={r["trades"]:3} win={r["win_rate_pct"]:6.2f}% pnl={r["net_pnl"]:10.2f} PF={r["profit_factor"]}')
    print()
    print("ENTRY TIME")
    for r in timeg:
        print(f'{r["group"]:12} trades={r["trades"]:3} win={r["win_rate_pct"]:6.2f}% pnl={r["net_pnl"]:10.2f} PF={r["profit_factor"]}')
    print()
    print("FILES:")
    print(" ",OUT/"full_history_forensic.html")
    print(" ",OUT/"all_trades_forensic.csv")
    print(" ",OUT/"daily_summary.csv")
    print(" ",OUT/"forensic_cause_summary.csv")
    print("="*120)

if __name__=="__main__":
    main()
