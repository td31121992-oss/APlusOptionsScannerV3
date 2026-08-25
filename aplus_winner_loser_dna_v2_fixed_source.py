from __future__ import annotations

"""
APlus Winner-vs-Loser DNA V2 — Entry Reconstruction
READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES

Purpose
-------
Reconstruct the exact entry-time market/scanner fingerprint for every historical
paper trade by mining:
- logs/scanner.log and scanner logs inside backup folders
- data/reports snapshots
- time_relative_rank_history
- leadership V6/V6.4 outputs
- intraday movement reports
- market watch / opening / technical / quote-tape snapshots
- current + backup paper trade history

Then compare historical winners vs losers using only data known AT OR BEFORE ENTRY.

No future leakage:
- exit reason, exit price, pnl magnitude, return, MFE/MAE, post-entry price,
  post-exit price, underlying future path are NOT predictors.

Important:
- This is research only.
- Sparse historical files may limit reconstruction coverage.
"""

import argparse
import csv
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
OUT = REPORTS / "winner_loser_dna_v2"
OUT.mkdir(parents=True, exist_ok=True)

TRADE_INPUTS = [
    REPORTS / "full_history_forensic_v2" / "all_trades_stock_vs_option.csv",
    REPORTS / "full_history_forensic" / "all_trades_forensic.csv",
    REPORTS / "paper_trade_history.csv",
    REPORTS / "paper_trades.csv",
]

SKIP_WORDS = (
    "\\venv\\","/venv/","\\.git\\","/.git/",
    "\\site-packages\\","/site-packages/",
    "\\__pycache__\\","/__pycache__/"
)

# Features that can legitimately exist at entry time.
FEATURES = [
    "trade_quality_score",
    "clean_trend_score",
    "trend_alignment_score",
    "movement_capture_score",
    "chase_risk_score",
    "relative_volume",
    "session_rvol",
    "recent_15m_rvol",
    "vwap_distance_pct",
    "adx",
    "rsi",
    "plus_di",
    "minus_di",
    "move_from_0915_open_pct",
    "recent_move_3m_pct",
    "recent_move_5m_pct",
    "recent_move_10m_pct",
    "recent_move_15m_pct",
    "recent_move_30m_pct",
    "rank",
    "rank_change_5m",
    "rank_change_10m",
    "rank_change_15m",
    "move_change_3m_pct",
    "move_change_5m_pct",
    "move_change_10m_pct",
    "leadership_score",
    "leadership_v6_qualified",
    "leadership_v64_fast_track",
    "signal_age_minutes",
    "entry_hour_decimal",
    "fresh_breakout_flag",
    "fresh_leg_flag",
    "reacceleration_flag",
    "stale_move_flag",
]

CATEGORICAL = [
    "direction",
    "option_type",
    "stage",
    "setup_family",
    "selection_tier",
    "pivot_state",
    "leadership_state",
    "leg_state",
    "paper_trade_status_at_entry",
]

LEAKAGE_KEYWORDS = (
    "exit","net_pnl","gross_pnl","return_percent","mfe","mae",
    "after_entry","after_exit","underlying_class","root_cause","forensic",
    "realized","winner","loser",
)

MAX_LOOKBACK_MIN = int(os.getenv("APLUS_DNA_V2_MAX_LOOKBACK_MIN", "8"))
MIN_RULE_TRADES = int(os.getenv("APLUS_DNA_V2_MIN_RULE_TRADES", "6"))
MIN_RULE_DAYS = int(os.getenv("APLUS_DNA_V2_MIN_RULE_DAYS", "2"))

def num(v: Any, d: float = 0.0) -> float:
    try:
        if v in (None, ""): return d
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def boo(v: Any) -> int:
    if isinstance(v,bool): return 1 if v else 0
    return 1 if str(v or "").strip().lower() in {"1","true","yes","y","on"} else 0

def parse_dt(v: Any) -> datetime | None:
    """Return all timestamps as naive IST wall-clock datetimes.

    Scanner logs are naive IST while API/report timestamps may carry +05:30.
    Normalizing both to naive IST prevents offset-aware vs offset-naive
    comparison failures without changing the observed market clock time.
    """
    s=str(v or "").strip()
    if not s:
        return None

    dt=None
    try:
        dt=datetime.fromisoformat(s)
    except Exception:
        pass

    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S","%d-%b-%Y %H:%M:%S","%Y/%m/%d %H:%M:%S"):
            try:
                dt=datetime.strptime(s[:19],fmt)
                break
            except Exception:
                pass

    if dt is None:
        return None

    if dt.tzinfo is not None:
        try:
            dt=dt.astimezone(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
        except Exception:
            dt=dt.replace(tzinfo=None)

    return dt

def norm_symbol(v: Any) -> str:
    return str(v or "").strip().upper()

def read_csv(path: Path) -> list[dict[str,Any]]:
    try:
        with path.open("r",encoding="utf-8-sig",newline="") as h:
            return [dict(r) for r in csv.DictReader(h)]
    except Exception:return []

def read_json_obj(path: Path) -> Any:
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return None

def json_rows(obj: Any) -> list[dict[str,Any]]:
    if isinstance(obj,list):
        return [dict(x) for x in obj if isinstance(x,dict)]
    if not isinstance(obj,dict):
        return []
    out=[]
    for k in ("rows","data","stocks","market_watch","candidates","items","history","signals","paper_trades","trades"):
        v=obj.get(k)
        if isinstance(v,list):
            out.extend(dict(x) for x in v if isinstance(x,dict))
        elif isinstance(v,dict):
            for sk,sv in v.items():
                if isinstance(sv,dict):
                    y=dict(sv);y.setdefault("symbol",sk);out.append(y)
    if not out and obj and all(isinstance(v,dict) for v in obj.values()):
        for sk,sv in obj.items():
            y=dict(sv);y.setdefault("symbol",sk);out.append(y)
    return out

def infer_day(path: Path) -> str:
    m=re.search(r"(20\d{2}-\d{2}-\d{2})",str(path))
    if m:return m.group(1)
    m=re.search(r"(20\d{2})(\d{2})(\d{2})",str(path))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""

def infer_time(path: Path) -> str:
    pats=(r"rank_(\d{4})",r"_(\d{4})(?:\.|_)",r"(\d{2})(\d{2})")
    for p in pats:
        m=re.search(p,path.name)
        if not m:continue
        if len(m.groups())==1:
            x=m.group(1)
            if len(x)==4:return f"{x[:2]}:{x[2:]}:00"
        elif len(m.groups())>=2:
            return f"{m.group(1)}:{m.group(2)}:00"
    return ""

def row_dt(r: dict[str,Any], path: Path) -> datetime | None:
    for k in ("timestamp","generated_at","time","datetime","updated_at","captured_at","scan_time","quote_time"):
        if r.get(k) not in (None,""):
            dt=parse_dt(r.get(k))
            if dt:return dt
    d=infer_day(path);t=infer_time(path)
    if d and t:
        try:return datetime.fromisoformat(d+"T"+t)
        except Exception:return None
    return None

def find_trade_source() -> Path:
    for p in TRADE_INPUTS:
        if p.exists():return p
    raise SystemExit("FAIL: run Full-History Forensic V2 first; no trade input found.")

def load_trades(path: Path) -> list[dict[str,Any]]:
    rows=read_csv(path)
    out=[]
    for r in rows:
        pnl=num(r.get("net_pnl"))
        if not r.get("entry_time"):continue
        x=dict(r)
        x["label_win"]=1 if pnl>0 else 0
        dt=parse_dt(r.get("entry_time"))
        x["entry_dt"]=dt
        x["entry_hour_decimal"]=(dt.hour+dt.minute/60) if dt else 0
        out.append(x)
    return out

def discover_sources(root: Path) -> tuple[list[Path],list[Path]]:
    structured=[];logs=[]
    for p in root.rglob("*"):
        if not p.is_file():continue
        low=str(p).lower()
        if any(w in low for w in SKIP_WORDS):continue
        if p.name.lower()=="scanner.log" or ("scanner" in p.name.lower() and p.suffix.lower()==".log"):
            logs.append(p);continue
        if p.suffix.lower() not in {".csv",".json"}:continue
        n=p.name.lower()
        if any(w in n for w in (
            "leadership","rank","movement","market_watch","entry_ready","opening",
            "technical","quote_tape","candidate","fresh_movement","wait_for_pullback",
            "near_miss","snapshot","intraday"
        )):
            structured.append(p)
    return structured,logs

# ---------- canonicalization ----------

ALIASES = {
    "trade_quality_score":("trade_quality_score","quality","quality_score"),
    "clean_trend_score":("clean_trend_score","clean_score"),
    "trend_alignment_score":("trend_alignment_score","alignment_score","trend_score"),
    "movement_capture_score":("movement_capture_score","movement_score"),
    "chase_risk_score":("chase_risk_score","chase_score"),
    "relative_volume":("relative_volume","rvol","session_rvol"),
    "session_rvol":("session_rvol","relative_volume","rvol"),
    "recent_15m_rvol":("recent_15m_rvol","rvol_15m"),
    "vwap_distance_pct":("vwap_distance_pct","vwap_distance_percent","vwap_pct"),
    "adx":("adx","adx_14"),
    "rsi":("rsi","rsi_14"),
    "plus_di":("plus_di","+di","pdi"),
    "minus_di":("minus_di","-di","mdi"),
    "move_from_0915_open_pct":("move_from_0915_open_pct","move_from_0915_open_percent","from_open_pct","move_from_open_pct"),
    "recent_move_3m_pct":("recent_move_3m_pct","move_3m_pct"),
    "recent_move_5m_pct":("recent_move_5m_pct","recent_move_5m_percent","move_5m_pct"),
    "recent_move_10m_pct":("recent_move_10m_pct","recent_move_10m_percent","move_10m_pct"),
    "recent_move_15m_pct":("recent_move_15m_pct","recent_move_15m_percent","move_15m_pct"),
    "recent_move_30m_pct":("recent_move_30m_pct","recent_move_30m_percent","move_30m_pct"),
    "rank":("rank","current_rank"),
    "rank_change_5m":("rank_change_5m","rank5","rank_delta_5m"),
    "rank_change_10m":("rank_change_10m","rank10","rank_delta_10m"),
    "rank_change_15m":("rank_change_15m","rank15","rank_delta_15m"),
    "move_change_3m_pct":("move_change_3m_pct","move3","move_delta_3m"),
    "move_change_5m_pct":("move_change_5m_pct","move5","move_delta_5m"),
    "move_change_10m_pct":("move_change_10m_pct","move10","move_delta_10m"),
    "leadership_score":("leadership_score","score"),
    "leadership_v6_qualified":("qualified_shadow","leadership_v6_qualified"),
    "leadership_v64_fast_track":("leadership_fast_track","leadership_v64_fast_track"),
    "fresh_breakout_flag":("fresh_15m_high","fresh_15m_low","fresh_30m_high","fresh_30m_low","fresh_day_high","fresh_day_low","opening_range_breakout"),
}

def get_alias(r: dict[str,Any], feature: str):
    for k in ALIASES.get(feature,(feature,)):
        if k in r and r.get(k) not in (None,""):
            return r.get(k)
    return None

def canonical_record(r: dict[str,Any], path: Path) -> dict[str,Any] | None:
    s=norm_symbol(r.get("symbol") or r.get("underlying_symbol") or r.get("stock_symbol"))
    dt=row_dt(r,path)
    if not s or not dt:return None
    out={"symbol":s,"timestamp":dt,"source_file":str(path)}
    for f in FEATURES:
        v=get_alias(r,f)
        if v is None:continue
        if f in ("leadership_v6_qualified","leadership_v64_fast_track","fresh_breakout_flag"):
            out[f]=boo(v)
        else:
            out[f]=num(v)
    for f in CATEGORICAL:
        if r.get(f) not in (None,""):out[f]=str(r.get(f))
    if r.get("paper_trade_status") not in (None,""):
        out["paper_trade_status_at_entry"]=str(r.get("paper_trade_status"))
    if r.get("leg_state") not in (None,""):out["leg_state"]=str(r.get("leg_state"))
    if r.get("state") not in (None,""):out["leadership_state"]=str(r.get("state"))
    return out

def load_structured_records(paths):
    by_day_symbol=defaultdict(lambda:defaultdict(list))
    stats=defaultdict(int)
    for p in paths:
        rows=read_csv(p) if p.suffix.lower()==".csv" else json_rows(read_json_obj(p))
        for r in rows:
            c=canonical_record(r,p)
            if not c:continue
            day=c["timestamp"].date().isoformat()
            by_day_symbol[day][c["symbol"]].append(c)
            stats[str(p)]+=1
    for day in by_day_symbol:
        for s in by_day_symbol[day]:
            by_day_symbol[day][s].sort(key=lambda x:x["timestamp"])
    return by_day_symbol,stats

# ---------- scanner log parsing ----------

LOG_TS=re.compile(r"^(20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
SYM_PATTERNS=[
    re.compile(r"\bsymbol=([A-Z0-9&\-]+)"),
    re.compile(r"\bsymbols=([A-Z0-9,&\-]+)"),
]

def parse_log_records(paths):
    by_day_symbol=defaultdict(lambda:defaultdict(list))
    stats=defaultdict(int)
    for p in paths:
        try:lines=p.read_text(encoding="utf-8",errors="ignore").splitlines()
        except Exception:continue
        for line in lines:
            mt=LOG_TS.match(line)
            if not mt:continue
            try:dt=datetime.strptime(mt.group(1),"%Y-%m-%d %H:%M:%S")
            except Exception:continue
            day=dt.date().isoformat()
            # Leadership list logs
            if "LEADERSHIP_V6_SHADOW" in line and "symbols=" in line:
                m=re.search(r"symbols=([A-Z0-9,&\-]+)",line)
                if m:
                    for sym in [x.strip().upper() for x in m.group(1).split(",") if x.strip()]:
                        by_day_symbol[day][sym].append({
                            "symbol":sym,"timestamp":dt,"source_file":str(p),
                            "leadership_v6_qualified":1,"leadership_state":"V6_SHADOW_HIT"
                        });stats[str(p)]+=1
            # Conversion audit / fallback logs
            m=re.search(r"symbol=([A-Z0-9&\-]+)",line)
            if m:
                sym=m.group(1).upper()
                rec={"symbol":sym,"timestamp":dt,"source_file":str(p)}
                if "PAPER conversion audit" in line:
                    rec["leadership_state"]="CONVERSION_AUDIT"
                    st=re.search(r"plan=(PASS|FAIL)",line)
                    if st:rec["paper_trade_status_at_entry"]="PLAN_"+st.group(1)
                if "OPTION_EXPIRY_FALLBACK" in line:
                    rec["leadership_state"]="OPTION_EXPIRY_FALLBACK"
                by_day_symbol[day][sym].append(rec);stats[str(p)]+=1
    for day in by_day_symbol:
        for s in by_day_symbol[day]:
            by_day_symbol[day][s].sort(key=lambda x:x["timestamp"])
    return by_day_symbol,stats

def merge_sources(structured,logs):
    out=defaultdict(lambda:defaultdict(list))
    for source in (structured,logs):
        for day,sm in source.items():
            for s,rows in sm.items():
                out[day][s].extend(rows)
    for day in out:
        for s in out[day]:
            out[day][s].sort(key=lambda x:x["timestamp"])
    return out

def entry_snapshot(trade, timeline):
    dt=trade.get("entry_dt")
    if not dt:return {},0
    day=str(trade.get("trading_date") or dt.date().isoformat())
    sym=norm_symbol(trade.get("symbol"))
    rows=timeline.get(day,{}).get(sym,[])
    if not rows:return {},0

    cutoff=dt-timedelta(minutes=MAX_LOOKBACK_MIN)
    relevant=[r for r in rows if cutoff<=r["timestamp"]<=dt]
    if not relevant:return {},0

    snap={}
    feature_sources={}
    first_signal=None
    latest_ts=None

    for r in relevant:
        latest_ts=r["timestamp"]
        if first_signal is None:
            first_signal=r["timestamp"]
        for f in FEATURES+CATEGORICAL:
            if f in r and r[f] not in (None,""):
                snap[f]=r[f]
                feature_sources[f]=r["source_file"]

    # Reconstruct age from earliest same-day record before entry, not just the lookback window.
    earlier=[r for r in rows if r["timestamp"]<=dt]
    if earlier:
        earliest=earlier[0]["timestamp"]
        snap["signal_age_minutes"]=max(0,(dt-earliest).total_seconds()/60)

    # Derive freshness/reacceleration from available acceleration.
    m5=num(snap.get("move_change_5m_pct"))
    m10=num(snap.get("move_change_10m_pct"))
    r5=num(snap.get("rank_change_5m"))
    v6=boo(snap.get("leadership_v6_qualified"))
    fresh=(m5>=0.25 and (r5>=5 or v6)) or m10>=0.40
    snap["fresh_leg_flag"]=1 if fresh else 0
    age=num(snap.get("signal_age_minutes"))
    snap["reacceleration_flag"]=1 if age>=60 and fresh else 0
    snap["stale_move_flag"]=1 if age>=60 and not fresh else 0

    # Entry hour always known.
    snap["entry_hour_decimal"]=trade.get("entry_hour_decimal",0)

    snap["_coverage_feature_count"]=sum(1 for f in FEATURES if f in snap and snap.get(f) not in (None,""))
    snap["_latest_snapshot_time"]=latest_ts.isoformat() if latest_ts else ""
    snap["_feature_sources"]=" | ".join(sorted(set(feature_sources.values())))
    return snap,snap["_coverage_feature_count"]

# ---------- DNA ----------

def pct(vals,q):
    if not vals:return 0
    s=sorted(vals);pos=(len(s)-1)*q;lo=int(math.floor(pos));hi=int(math.ceil(pos))
    if lo==hi:return s[lo]
    w=pos-lo;return s[lo]*(1-w)+s[hi]*w

def feature_dna(rows):
    wins=[r for r in rows if r["label_win"]==1]
    losses=[r for r in rows if r["label_win"]==0]
    out=[]
    for f in FEATURES:
        if any(k in f.lower() for k in LEAKAGE_KEYWORDS):continue
        w=[num(r.get(f)) for r in wins if r.get(f) not in (None,"")]
        l=[num(r.get(f)) for r in losses if r.get(f) not in (None,"")]
        if len(w)<2 or len(l)<5:continue
        wm=median(w);lm=median(l);allv=w+l;span=pct(allv,.9)-pct(allv,.1)
        sep=(wm-lm)/span if span else 0
        out.append({
            "feature":f,"winner_n":len(w),"loser_n":len(l),
            "winner_mean":round(mean(w),6),"loser_mean":round(mean(l),6),
            "winner_median":round(wm,6),"loser_median":round(lm,6),
            "normalized_median_separation":round(sep,6),
            "abs_separation":round(abs(sep),6),
            "winner_like_direction":"HIGHER" if sep>0 else "LOWER",
        })
    out.sort(key=lambda x:x["abs_separation"],reverse=True)
    return out

def cat_dna(rows):
    overall=sum(r["label_win"] for r in rows)/len(rows) if rows else 0
    out=[]
    for f in CATEGORICAL:
        by=defaultdict(list)
        for r in rows:
            v=str(r.get(f) or "").strip()
            if v:by[v].append(r)
        for v,xs in by.items():
            if len(xs)<3:continue
            wr=sum(r["label_win"] for r in xs)/len(xs)
            out.append({
                "feature":f,"value":v,"trades":len(xs),"wins":sum(r["label_win"] for r in xs),
                "win_rate_pct":round(wr*100,2),
                "lift_vs_overall":round(wr/overall,3) if overall else 0,
                "net_pnl":round(sum(num(r.get("net_pnl")) for r in xs),2)
            })
    out.sort(key=lambda x:(x["lift_vs_overall"],x["trades"]),reverse=True)
    return out

def thresholds(rows,dna_row):
    f=dna_row["feature"]
    vals=[num(r.get(f)) for r in rows if r.get(f) not in (None,"")]
    if len(vals)<10:return []
    qs=(.4,.5,.6,.7,.8,.9)
    th=sorted(set(round(pct(vals,q),6) for q in qs))
    op=">=" if dna_row["winner_like_direction"]=="HIGHER" else "<="
    return [(f,op,t) for t in th]

def match(r,rule):
    f,op,t=rule
    if r.get(f) in (None,""):return False
    v=num(r.get(f))
    return v>=t if op==">=" else v<=t

def eval_rule(rows,rules):
    xs=[r for r in rows if all(match(r,ru) for ru in rules)]
    if not xs:return None
    wins=sum(r["label_win"] for r in xs)
    pnl=sum(num(r.get("net_pnl")) for r in xs)
    return {
        "trades":len(xs),"wins":wins,"losses":len(xs)-wins,
        "win_rate_pct":round(wins/len(xs)*100,2),
        "net_pnl":round(pnl,2),"expectancy":round(pnl/len(xs),2),
        "days":len(set(str(r.get("trading_date") or "") for r in xs))
    }

def rule_text(rules):
    return " AND ".join(f"{f} {op} {t}" for f,op,t in rules)

def search_rules(rows,dna):
    top=[d for d in dna if d["abs_separation"]>0][:10]
    flat=[ru for d in top for ru in thresholds(rows,d)]
    out=[];seen=set()
    for k in (1,2,3):
        for rules in combinations(flat,k):
            feats=[r[0] for r in rules]
            if len(set(feats))<k:continue
            key=tuple(sorted(rules))
            if key in seen:continue
            seen.add(key)
            ev=eval_rule(rows,rules)
            if not ev or ev["trades"]<MIN_RULE_TRADES or ev["days"]<MIN_RULE_DAYS:continue
            out.append({"rule":rule_text(rules),**ev})
    out.sort(key=lambda x:(x["win_rate_pct"],x["expectancy"],x["trades"]),reverse=True)
    return out[:5000]

def parse_rule(text):
    out=[]
    for part in text.split(" AND "):
        bits=part.rsplit(" ",2)
        if len(bits)==3:
            out.append((bits[0],bits[1],float(bits[2])))
    return out

# True holdout:
# For each held-out day, rules are discovered ONLY from remaining days.
def true_leave_one_day_out(rows):
    days=sorted(set(str(r.get("trading_date") or "") for r in rows if r.get("trading_date")))
    folds=[]
    for held in days:
        train=[r for r in rows if str(r.get("trading_date") or "")!=held]
        test=[r for r in rows if str(r.get("trading_date") or "")==held]
        if not train or not test:continue
        dna=feature_dna(train)
        candidates=search_rules(train,dna)
        if not candidates:
            folds.append({"held_out_day":held,"rule":"","test_trades":0,"test_wins":0,"test_losses":0,"test_win_rate_pct":0,"test_net_pnl":0,"test_expectancy":0})
            continue
        # Select best training rule, then freeze it before touching held-out day.
        chosen=candidates[0]
        rules=parse_rule(chosen["rule"])
        ev=eval_rule(test,rules)
        if not ev:
            ev={"trades":0,"wins":0,"losses":0,"win_rate_pct":0,"net_pnl":0,"expectancy":0,"days":0}
        folds.append({
            "held_out_day":held,
            "training_rule":chosen["rule"],
            "training_trades":chosen["trades"],
            "training_win_rate_pct":chosen["win_rate_pct"],
            "training_expectancy":chosen["expectancy"],
            "test_trades":ev["trades"],
            "test_wins":ev["wins"],
            "test_losses":ev["losses"],
            "test_win_rate_pct":ev["win_rate_pct"],
            "test_net_pnl":ev["net_pnl"],
            "test_expectancy":ev["expectancy"],
        })
    return folds

def score_rows(rows,dna):
    top=[d for d in dna if d["abs_separation"]>0][:10]
    out=[]
    for r in rows:
        score=0;used=0
        for d in top:
            f=d["feature"]
            if r.get(f) in (None,""):continue
            wm=num(d["winner_median"]);lm=num(d["loser_median"]);den=abs(wm-lm)
            if den<1e-9:continue
            direction=1 if wm>lm else -1
            c=direction*(num(r.get(f))-lm)/den
            c=max(-2,min(2,c))
            score+=c*max(.05,num(d["abs_separation"]));used+=1
        x=dict(r);x["dna_v2_score"]=round(score/used,6) if used else 0;x["dna_features_used"]=used
        out.append(x)
    return out

def ladder(rows):
    xs=sorted(rows,key=lambda r:num(r.get("dna_v2_score")),reverse=True)
    ns=[5,10,15,20,25,30,40,50,75,100,150,len(xs)]
    out=[];seen=set()
    for n in ns:
        n=min(n,len(xs))
        if n<=0 or n in seen:continue
        seen.add(n);sub=xs[:n];wins=sum(r["label_win"] for r in sub);pnl=sum(num(r.get("net_pnl")) for r in sub)
        out.append({"top_n":n,"wins":wins,"losses":n-wins,"win_rate_pct":round(wins/n*100,2),
                    "net_pnl":round(pnl,2),"expectancy":round(pnl/n,2),
                    "unique_days":len(set(str(r.get("trading_date") or "") for r in sub))})
    return out

def write_csv(path,rows):
    if not rows:
        path.write_text("",encoding="utf-8");return
    fields=[];seen=set()
    for r in rows:
        for k in r:
            if k not in seen:seen.add(k);fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)

def html(summary,dna,cat,rules,folds,ladder_rows,path):
    def tbl(rows,cols):
        hd="".join(f"<th>{c}</th>" for c in cols)
        bd="".join("<tr>"+"".join(f"<td>{r.get(c,'')}</td>" for c in cols)+"</tr>" for r in rows)
        return f"<table><tr>{hd}</tr>{bd}</table>"
    h=f"""<!doctype html><html><head><meta charset='utf-8'><title>APlus DNA V2</title>
<style>body{{font-family:Segoe UI,Arial;background:#0b1020;color:#e8eef8;margin:25px}}table{{width:100%;border-collapse:collapse;background:#121a2d;margin-bottom:28px}}th,td{{padding:7px;border-bottom:1px solid #29344d;font-size:12px;text-align:left}}th{{color:#91a3c2}}.warn{{background:#3b2d12;padding:12px;border-radius:10px}}</style></head><body>
<h1>APlus Winner-vs-Loser DNA V2 — Reconstructed Entry Fingerprint</h1>
<div class='warn'>Research only. Reconstruction coverage={summary["reconstruction_coverage_pct"]}%. Winners={summary["wins"]}, days={summary["days"]}. High historical accuracy can be overfit.</div>
<h2>Numeric DNA</h2>{tbl(dna[:25],["feature","winner_n","loser_n","winner_median","loser_median","normalized_median_separation","winner_like_direction"])}
<h2>Categorical DNA</h2>{tbl(cat[:30],["feature","value","trades","wins","win_rate_pct","lift_vs_overall","net_pnl"])}
<h2>Best In-Sample Rules</h2>{tbl(rules[:30],["rule","trades","wins","losses","win_rate_pct","net_pnl","expectancy","days"])}
<h2>TRUE Leave-One-Day-Out</h2>{tbl(folds,["held_out_day","training_rule","training_trades","training_win_rate_pct","test_trades","test_wins","test_losses","test_win_rate_pct","test_net_pnl","test_expectancy"])}
<h2>Selectivity Ladder</h2>{tbl(ladder_rows,["top_n","wins","losses","win_rate_pct","net_pnl","expectancy","unique_days"])}
</body></html>"""
    path.write_text(h,encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=str(ROOT))
    args=ap.parse_args()
    root=Path(args.root).resolve()

    trade_source=find_trade_source()
    trades=load_trades(trade_source)
    structured_paths,log_paths=discover_sources(root)
    structured,structured_stats=load_structured_records(structured_paths)
    logs,log_stats=parse_log_records(log_paths)
    timeline=merge_sources(structured,logs)

    enriched=[];covered=0
    for t in trades:
        snap,count=entry_snapshot(t,timeline)
        x=dict(t)
        x.update(snap)
        if count>0:covered+=1
        enriched.append(x)

    dna=feature_dna(enriched)
    cat=cat_dna(enriched)
    rules=search_rules(enriched,dna)
    folds=true_leave_one_day_out(enriched)
    scored=score_rows(enriched,dna)
    ladder_rows=ladder(scored)

    wins=sum(r["label_win"] for r in enriched)
    summary={
        "trade_source":str(trade_source),
        "trades":len(enriched),"wins":wins,"losses":len(enriched)-wins,
        "win_rate_pct":round(wins/len(enriched)*100,2) if enriched else 0,
        "days":len(set(str(r.get("trading_date") or "") for r in enriched if r.get("trading_date"))),
        "reconstructed_trades":covered,
        "reconstruction_coverage_pct":round(covered/len(enriched)*100,2) if enriched else 0,
        "structured_source_files_used":len(structured_stats),
        "scanner_log_files_used":len(log_stats),
        "numeric_features_evaluated":len(dna),
        "categorical_groups_evaluated":len(cat),
        "candidate_rules":len(rules),
        "true_leave_one_day_out":True,
        "future_information_used_as_predictor":False,
        "premium_used_as_predictor":False,
        "read_only":True,"dhan_calls":False,"strategy_changes":False,
    }

    write_csv(OUT/"reconstructed_entry_fingerprints.csv",enriched)
    write_csv(OUT/"numeric_dna.csv",dna)
    write_csv(OUT/"categorical_dna.csv",cat)
    write_csv(OUT/"selective_rules_in_sample.csv",rules)
    write_csv(OUT/"true_leave_one_day_out.csv",folds)
    write_csv(OUT/"dna_v2_scores.csv",scored)
    write_csv(OUT/"selectivity_ladder.csv",ladder_rows)
    write_csv(OUT/"structured_sources.csv",[{"file":k,"records":v} for k,v in sorted(structured_stats.items(),key=lambda x:x[1],reverse=True)])
    write_csv(OUT/"log_sources.csv",[{"file":k,"records":v} for k,v in sorted(log_stats.items(),key=lambda x:x[1],reverse=True)])
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    html(summary,dna,cat,rules,folds,ladder_rows,OUT/"winner_loser_dna_v2.html")

    print("="*132)
    print("APLUS WINNER-vs-LOSER DNA V2 — RECONSTRUCTED ENTRY FINGERPRINT")
    print("READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES - TRUE DAY HOLDOUT")
    print("="*132)
    for k,v in summary.items():print(f"{k:42}: {v}")

    print("\nTOP NUMERIC WINNER DNA")
    for x in dna[:15]:
        print(f'{x["feature"]:30} Wmed={x["winner_median"]:10.4f} Lmed={x["loser_median"]:10.4f} sep={x["normalized_median_separation"]:+.4f} {x["winner_like_direction"]}')

    print("\nTOP IN-SAMPLE RULES")
    for x in rules[:15]:
        print(f'{x["win_rate_pct"]:6.2f}% trades={x["trades"]:3} W={x["wins"]:3} L={x["losses"]:3} exp={x["expectancy"]:9.2f} {x["rule"]}')

    print("\nTRUE LEAVE-ONE-DAY-OUT")
    for x in folds:
        print(f'{x["held_out_day"]} trainWin={x.get("training_win_rate_pct",0):6.2f}% testTrades={x["test_trades"]:3} testW={x["test_wins"]:3} testL={x["test_losses"]:3} testWin={x["test_win_rate_pct"]:6.2f}% testPnL={x["test_net_pnl"]:10.2f}')
        if x.get("training_rule"):print("   ",x["training_rule"])

    print("\nDNA V2 SELECTIVITY LADDER")
    for x in ladder_rows:
        print(f'Top {x["top_n"]:3}: W={x["wins"]:3} L={x["losses"]:3} win={x["win_rate_pct"]:6.2f}% pnl={x["net_pnl"]:11.2f} exp={x["expectancy"]:9.2f}')

    print("\nOPEN:",OUT/"winner_loser_dna_v2.html")
    print("="*132)

if __name__=="__main__":
    main()
