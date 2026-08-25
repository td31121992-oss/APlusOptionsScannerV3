from __future__ import annotations

"""
APlus Leadership V6.4 SHADOW Research Engine

ZERO DHAN CALLS.
ZERO OPTION/FUTURES ORDER AUTHORITY.
ZERO PRODUCTION STRATEGY CHANGES.

Reads existing APlus reports and independently classifies:
1) LEADERSHIP_FAST_TRACK
2) OPTION_PREMIUM_FRAGILITY
3) FRESH_NEW_LEG / REACCELERATION_NEW_LEG / STALE_MOVE
4) FUTURES_PAPER_RECOMMENDED

The engine persists its own short history so a genuinely new 13:10 move can
qualify even if the symbol also moved earlier in the day.
"""

import csv, json, math, os, tempfile, time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

IST=ZoneInfo("Asia/Kolkata")
ROOT=Path(__file__).resolve().parent
REPORTS=ROOT/"data"/"reports"
STATE_DIR=ROOT/"data"/"leadership_v6_4_shadow"
STATE_DIR.mkdir(parents=True,exist_ok=True)

ENTRY_READY=REPORTS/"intraday_entry_ready.csv"
V6=REPORTS/"leadership_v6_shadow_latest.csv"
MARKET_JSON=REPORTS/"fno_market_watch_latest.json"
MARKET_CSV=REPORTS/"fno_market_watch_latest.csv"
PAPER_TRADES=REPORTS/"paper_trades.csv"
LATEST_JSON=REPORTS/"leadership_v6_4_shadow_latest.json"
LATEST_CSV=REPORTS/"leadership_v6_4_shadow_latest.csv"
FUTURES_BRIDGE=REPORTS/"leadership_v6_4_futures_bridge_latest.csv"
EVENTS=STATE_DIR/"events.csv"
STATE_JSON=STATE_DIR/"runtime_state.json"

FAST_Q=float(os.getenv("APLUS_V64_FAST_Q","90"))
FAST_CLEAN=float(os.getenv("APLUS_V64_FAST_CLEAN","90"))
FAST_RVOL=float(os.getenv("APLUS_V64_FAST_RVOL","2.0"))
FAST_ALIGN=float(os.getenv("APLUS_V64_FAST_ALIGN","55"))
NEW_LEG_MOVE_5M=float(os.getenv("APLUS_V64_NEW_LEG_MOVE_5M","0.25"))
NEW_LEG_MOVE_10M=float(os.getenv("APLUS_V64_NEW_LEG_MOVE_10M","0.40"))
RANK_IMPROVE_5M=int(os.getenv("APLUS_V64_RANK_IMPROVE_5M","5"))
STALE_MINUTES=int(os.getenv("APLUS_V64_STALE_MINUTES","60"))
CHEAP_PREMIUM=float(os.getenv("APLUS_V64_CHEAP_PREMIUM","15"))
WIDE_SPREAD=float(os.getenv("APLUS_V64_WIDE_SPREAD","3.0"))

def num(v,d=0.0):
    try:
        if v in (None,""): return d
        x=float(v); return x if math.isfinite(x) else d
    except Exception:return d

def boo(v):
    if isinstance(v,bool):return v
    return str(v or "").strip().lower() in {"1","true","yes","y","on"}

def read_csv(path):
    if not path.exists():return []
    try:
        with path.open("r",encoding="utf-8-sig",newline="") as h:return [dict(x) for x in csv.DictReader(h)]
    except Exception:return []

def read_json(path):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return {}

def atomic(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="") as h:h.write(text);h.flush()
        last=None
        for i in range(7):
            try:os.replace(tmp,path);return
            except PermissionError as e:last=e;time.sleep(.04*(2**i))
        if last:raise last
    finally:
        try:
            if os.path.exists(tmp):os.unlink(tmp)
        except OSError:pass

def parse_dt(v):
    try:return datetime.fromisoformat(str(v)).astimezone(IST)
    except Exception:return None

def market_rows():
    obj=read_json(MARKET_JSON);rows=[]
    if isinstance(obj,dict):
        for k in ("rows","stocks","market_watch","data"):
            if isinstance(obj.get(k),list):rows=obj[k];break
    if not rows:rows=read_csv(MARKET_CSV)
    return rows

def keymap(rows):
    return {str(r.get("symbol") or "").upper():r for r in rows if isinstance(r,dict)}

def vwap_aligned(direction,vwap):
    return vwap>0 if direction=="BULLISH" else vwap<0

class V64:
    def __init__(self):
        self.first_seen={}
        self.history=defaultdict(lambda:deque(maxlen=80))
        self._load()

    def _load(self):
        obj=read_json(STATE_JSON)
        if not isinstance(obj,dict):return
        self.first_seen={k:v for k,v in (obj.get("first_seen") or {}).items()}
        for s,rows in (obj.get("history") or {}).items():
            dq=deque(maxlen=80)
            for r in rows:
                if isinstance(r,dict):dq.append(r)
            self.history[s]=dq

    def _save(self,now):
        atomic(STATE_JSON,json.dumps({
            "updated_at":now.isoformat(),
            "first_seen":self.first_seen,
            "history":{s:list(v) for s,v in self.history.items()},
        },indent=2))

    def _recent(self,symbol,minutes,now):
        cutoff=now.timestamp()-minutes*60
        xs=[x for x in self.history[symbol] if num(x.get("ts"))<=cutoff]
        return xs[-1] if xs else None

    def evaluate(self,now=None):
        now=(now or datetime.now(IST)).astimezone(IST)
        er=keymap(read_csv(ENTRY_READY));v6=keymap(read_csv(V6));mw=keymap(market_rows())
        symbols=sorted(set(er)|set(v6)|set(mw))
        paper=read_csv(PAPER_TRADES)
        latest_trade={}
        for t in paper:
            latest_trade[str(t.get("symbol") or "").upper()]=t

        rows=[]
        for s in symbols:
            a=er.get(s,{});l=v6.get(s,{});m=mw.get(s,{})
            direction=str(a.get("direction") or l.get("direction") or "").upper()
            if direction not in {"BULLISH","BEARISH"}:
                fd=num(m.get("from_open_pct") or m.get("move_from_open_percent"))
                direction="BULLISH" if fd>0 else ("BEARISH" if fd<0 else "")
            if not direction:continue

            move=num(l.get("directional_move_pct"))
            if move==0:
                raw=num(m.get("from_open_pct") or m.get("move_from_open_percent"))
                move=raw if direction=="BULLISH" else -raw
            rank=int(num(l.get("rank"),999))
            q=num(a.get("trade_quality_score") or l.get("trade_quality_score"))
            clean=num(a.get("clean_trend_score") or l.get("clean_trend_score"))
            align=num(a.get("trend_alignment_score") or l.get("trend_alignment_score"))
            rvol=num(a.get("relative_volume") or l.get("relative_volume"))
            vwap=num(a.get("vwap_distance_percent"))
            v6q=boo(l.get("qualified_shadow"))
            r5=int(num(l.get("rank_change_5m")))
            m3=num(l.get("move_change_3m_pct"))
            m5=num(l.get("move_change_5m_pct"))
            r10=0;m10=0.0

            if s not in self.first_seen and (q>0 or v6q or s in er):
                self.first_seen[s]=now.isoformat()

            self.history[s].append({"ts":now.timestamp(),"move":move,"rank":rank})
            old5=self._recent(s,5,now);old10=self._recent(s,10,now)
            if old5:
                m5=move-num(old5.get("move"));r5=int(num(old5.get("rank"),rank)-rank)
            if old10:
                m10=move-num(old10.get("move"));r10=int(num(old10.get("rank"),rank)-rank)

            age=0.0
            fs=parse_dt(self.first_seen.get(s))
            if fs:age=max(0,(now-fs).total_seconds()/60)

            fast=(
                q>=FAST_Q and clean>=FAST_CLEAN and rvol>=FAST_RVOL
                and align>=FAST_ALIGN and vwap_aligned(direction,vwap)
            ) or (
                v6q and q>=85 and clean>=85 and rvol>=1.5 and vwap_aligned(direction,vwap)
            )

            fresh_leg=(m5>=NEW_LEG_MOVE_5M and (r5>=RANK_IMPROVE_5M or v6q)) or m10>=NEW_LEG_MOVE_10M
            reaccel=age>=STALE_MINUTES and fresh_leg
            stale=age>=STALE_MINUTES and not fresh_leg

            if reaccel:leg="REACCELERATION_NEW_LEG"
            elif fresh_leg:leg="FRESH_NEW_LEG"
            elif stale:leg="STALE_MOVE"
            else:leg="DEVELOPING"

            t=latest_trade.get(s,{})
            premium=num(t.get("entry_price") or t.get("option_ltp"))
            spread=num(t.get("spread_percent"))
            fragile=(premium>0 and premium<=CHEAP_PREMIUM) or (spread>WIDE_SPREAD and spread>0)

            status=str(a.get("paper_trade_status") or "")
            option_error=str(a.get("option_error") or "")
            option_block=("OPTION_PLAN_FAILED" in status or "SAFETY_BLOCKED" in status or bool(option_error))
            futures_rec=bool(fast and leg!="STALE_MOVE" and (option_block or fragile or status.startswith("A_PLUS_WAIT") or status.startswith("V2_")))

            lane=[]
            if fast:lane.append("LEADERSHIP_FAST_TRACK")
            if fragile:lane.append("OPTION_PREMIUM_FRAGILITY")
            lane.append(leg)
            if futures_rec:lane.append("FUTURES_PAPER_RECOMMENDED")

            row={
                "timestamp":now.isoformat(),"symbol":s,"direction":direction,
                "leadership_fast_track":fast,"leg_state":leg,"age_minutes":round(age,1),
                "rank":rank,"directional_move_pct":round(move,4),
                "rank_change_5m":r5,"rank_change_10m":r10,
                "move_change_3m_pct":round(m3,4),"move_change_5m_pct":round(m5,4),"move_change_10m_pct":round(m10,4),
                "trade_quality_score":q,"clean_trend_score":clean,"trend_alignment_score":align,"relative_volume":rvol,
                "vwap_distance_percent":vwap,"v6_qualified":v6q,
                "production_status":status,"option_error":option_error,
                "option_entry_premium_if_traded":premium,"option_spread_pct_if_traded":spread,
                "option_premium_fragile":fragile,
                "futures_paper_recommended":futures_rec,
                "research_lane":" | ".join(lane),
            }
            rows.append(row)

        rows.sort(key=lambda r:(r["leadership_fast_track"],r["futures_paper_recommended"],r["trade_quality_score"],r["relative_volume"]),reverse=True)
        self._write(rows,now)
        self._save(now)
        return rows

    def _write(self,rows,now):
        atomic(LATEST_JSON,json.dumps({"updated_at":now.isoformat(),"research_only":True,"production_changes":False,"dhan_calls":False,"rows":rows},indent=2))
        if rows:
            import io
            s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows);atomic(LATEST_CSV,"\ufeff"+s.getvalue())
            bridge=[r for r in rows if r["futures_paper_recommended"]]
            if bridge:
                s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=list(bridge[0]));w.writeheader();w.writerows(bridge);atomic(FUTURES_BRIDGE,"\ufeff"+s.getvalue())
        self._events(rows)

    def _events(self,rows):
        interesting=[r for r in rows if r["leadership_fast_track"] or r["leg_state"]=="REACCELERATION_NEW_LEG" or r["futures_paper_recommended"]]
        if not interesting:return
        exists=EVENTS.exists()
        with EVENTS.open("a",encoding="utf-8-sig",newline="") as h:
            w=csv.DictWriter(h,fieldnames=list(interesting[0]))
            if not exists:w.writeheader()
            w.writerows(interesting)

def run_loop(interval=30):
    e=V64()
    print("="*112)
    print("APlus Leadership V6.4 SHADOW")
    print("ZERO DHAN CALLS - ZERO PRODUCTION CHANGES - FUTURES RECOMMENDATION IS PAPER/RESEARCH ONLY")
    print("="*112)
    while True:
        rows=e.evaluate()
        hot=[r for r in rows if r["leadership_fast_track"]]
        fut=[r for r in rows if r["futures_paper_recommended"]]
        print(f"{datetime.now(IST).strftime('%H:%M:%S')} V6.4 fast_track={len(hot)} futures_paper={len(fut)} top="+",".join(r["symbol"] for r in hot[:8]))
        time.sleep(max(10,int(interval)))

if __name__=="__main__":
    run_loop()
