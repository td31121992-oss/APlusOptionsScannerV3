from __future__ import annotations

"""
APlus Decision Evidence Recorder V1
OBSERVATION ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES

Continuously records the full decision fingerprint for:
- ENTRY_READY
- FRESH_MOVEMENT
- WAIT_FOR_PULLBACK
- NEAR_MISS
- Leadership V6
- Leadership V6.4
- scanner.log conversion / expiry / rejection evidence
- actual PAPER trade entries/exits
- subsequent UNDERLYING path from the existing saved market-watch feed

No broker calls. No production scanner patch. No live/paper order authority.
"""

import csv
import json
import math
import os
import re
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"
LOGS = ROOT / "logs"
OUT = DATA / "decision_evidence"
OUT.mkdir(parents=True, exist_ok=True)

ENTRY_READY = REPORTS / "intraday_entry_ready.csv"
FRESH = REPORTS / "intraday_fresh_movement.csv"
WAIT = REPORTS / "intraday_wait_for_pullback.csv"
NEAR = REPORTS / "intraday_near_misses.csv"
V6_CSV = REPORTS / "leadership_v6_shadow_latest.csv"
V6_JSON = REPORTS / "leadership_v6_shadow_latest.json"
V64_CSV = REPORTS / "leadership_v6_4_shadow_latest.csv"
V64_JSON = REPORTS / "leadership_v6_4_shadow_latest.json"
MARKET_JSON = REPORTS / "fno_market_watch_latest.json"
MARKET_CSV = REPORTS / "fno_market_watch_latest.csv"
PAPER_CSV = REPORTS / "paper_trades.csv"
PAPER_JSON = REPORTS / "paper_trades_latest.json"
SCANNER_LOG = LOGS / "scanner.log"

EVENTS_CSV = OUT / "decision_events.csv"
SNAPSHOTS_CSV = OUT / "candidate_snapshots.csv"
TRADE_PATH_CSV = OUT / "trade_underlying_path.csv"
LATEST_JSON = OUT / "latest.json"
STATE_JSON = OUT / "recorder_state.json"

POLL_SECONDS = int(os.getenv("APLUS_DECISION_RECORDER_POLL_SECONDS", "15"))
SNAPSHOT_DEDUPE_SECONDS = int(os.getenv("APLUS_DECISION_RECORDER_DEDUPE_SECONDS", "45"))
PATH_HORIZONS = (1, 3, 5, 10, 15, 30, 60)

def num(v: Any, d: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return d
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def boo(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in {"1","true","yes","y","on"}

def now_ist() -> datetime:
    return datetime.now(IST)

def norm_symbol(v: Any) -> str:
    return str(v or "").strip().upper()

def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as h:
            return [dict(r) for r in csv.DictReader(h)]
    except Exception:
        return []

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def json_rows(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return [dict(x) for x in obj if isinstance(x, dict)]
    if not isinstance(obj, dict):
        return []
    for k in ("rows","data","stocks","market_watch","candidates","paper_trades","trades"):
        v = obj.get(k)
        if isinstance(v, list):
            return [dict(x) for x in v if isinstance(x, dict)]
    if isinstance(obj.get("symbols"), dict):
        out=[]
        for k,v in obj["symbols"].items():
            if isinstance(v, dict):
                x=dict(v); x.setdefault("symbol", k); out.append(x)
        return out
    return []

def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp = tempfile.mkstemp(prefix=path.name+".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="") as h:
            h.write(text); h.flush()
        last=None
        for i in range(7):
            try:
                os.replace(tmp,path); return
            except PermissionError as e:
                last=e; time.sleep(.03*(2**i))
        if last: raise last
    finally:
        try:
            if os.path.exists(tmp): os.unlink(tmp)
        except OSError:
            pass

def append_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 3
    fields=[]
    if exists:
        try:
            with path.open("r",encoding="utf-8-sig",newline="") as h:
                fields = next(csv.reader(h))
        except Exception:
            fields=[]
    if not fields:
        seen=set()
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.add(k); fields.append(k)
    # Keep schema stable. Extra newly-discovered keys go into extras_json.
    normalized=[]
    for r in rows:
        x={k:r.get(k,"") for k in fields}
        extras={k:v for k,v in r.items() if k not in fields and v not in (None,"")}
        if "extras_json" in fields:
            x["extras_json"]=json.dumps(extras,ensure_ascii=False) if extras else ""
        normalized.append(x)
    if not exists and "extras_json" not in fields:
        fields.append("extras_json")
        normalized=[]
        for r in rows:
            x={k:r.get(k,"") for k in fields}
            x["extras_json"]=""
            normalized.append(x)
    with path.open("a",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction="ignore")
        if not exists: w.writeheader()
        w.writerows(normalized)

def parse_dt(v: Any) -> datetime | None:
    s=str(v or "").strip()
    if not s: return None
    try:
        dt=datetime.fromisoformat(s)
    except Exception:
        dt=None
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S","%d-%b-%Y %H:%M:%S"):
            try:
                dt=datetime.strptime(s[:19],fmt)
                break
            except Exception:
                pass
    if dt is None: return None
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=IST)
    else:
        dt=dt.astimezone(IST)
    return dt

def market_rows() -> list[dict[str, Any]]:
    obj=read_json(MARKET_JSON)
    rows=json_rows(obj)
    return rows if rows else read_csv(MARKET_CSV)

def market_map() -> dict[str, dict[str, Any]]:
    return {norm_symbol(r.get("symbol")):r for r in market_rows() if norm_symbol(r.get("symbol"))}

def underlying_ltp(row: Mapping[str, Any]) -> float:
    for k in ("ltp","last_price","current_price","price","close"):
        x=num(row.get(k))
        if x>0:return x
    return 0.0

def directional_move(direction: str, entry: float, current: float) -> float | None:
    if entry<=0 or current<=0:return None
    raw=(current-entry)/entry*100
    return raw if direction=="BULLISH" else -raw

FINGERPRINT_FIELDS = (
    "symbol","direction","stage","setup_family","selection_tier","pivot_state",
    "trade_quality_score","movement_capture_score","trend_alignment_score",
    "clean_trend_score","chase_risk_score","relative_volume","session_rvol",
    "recent_15m_rvol","vwap_distance_percent","vwap_distance_pct","adx","rsi",
    "plus_di","minus_di","recent_move_3m_pct","recent_move_5m_pct",
    "recent_move_10m_pct","recent_move_15m_pct","recent_move_30m_pct",
    "move_from_0915_open_pct","move_from_0915_open_percent",
    "fresh_15m_high","fresh_15m_low","fresh_30m_high","fresh_30m_low",
    "fresh_day_high","fresh_day_low","opening_range_breakout",
    "paper_trade_status","rejection_reason","option_error","safety_decision",
    "safety_block_reasons","option_type","strike","expiry","entry_price",
)

def fingerprint(source: str, r: Mapping[str, Any], ts: datetime) -> dict[str, Any]:
    out={
        "event_time":ts.isoformat(),
        "trading_date":ts.date().isoformat(),
        "source":source,
        "event_type":"CANDIDATE_SNAPSHOT",
    }
    for k in FINGERPRINT_FIELDS:
        if k in r:
            out[k]=r.get(k)
    out["symbol"]=norm_symbol(out.get("symbol"))
    # Useful canonical aliases
    out["vwap_distance_pct"]=num(r.get("vwap_distance_pct") or r.get("vwap_distance_percent"))
    out["relative_volume"]=num(r.get("relative_volume") or r.get("session_rvol"))
    out["fresh_breakout_flag"]=int(any(boo(r.get(k)) for k in (
        "fresh_15m_high","fresh_15m_low","fresh_30m_high","fresh_30m_low",
        "fresh_day_high","fresh_day_low","opening_range_breakout"
    )))
    return out

class Recorder:
    def __init__(self):
        self.state=self._load_state()
        self.last_snapshot={}
        self.paper_seen=set(self.state.get("paper_seen",[]))
        self.log_offset=int(self.state.get("log_offset",0))
        self.trade_track=self.state.get("trade_track",{})
        self.first_candidate=self.state.get("first_candidate",{})

    def _load_state(self):
        obj=read_json(STATE_JSON)
        return obj if isinstance(obj,dict) else {}

    def _save_state(self):
        obj={
            "updated_at":now_ist().isoformat(),
            "paper_seen":sorted(self.paper_seen),
            "log_offset":self.log_offset,
            "trade_track":self.trade_track,
            "first_candidate":self.first_candidate,
        }
        atomic_text(STATE_JSON,json.dumps(obj,indent=2))

    def _candidate_files(self):
        return (
            ("ENTRY_READY",ENTRY_READY),
            ("FRESH_MOVEMENT",FRESH),
            ("WAIT_FOR_PULLBACK",WAIT),
            ("NEAR_MISS",NEAR),
        )

    def capture_candidates(self, now: datetime) -> list[dict[str, Any]]:
        events=[]
        snapshots=[]
        for source,path in self._candidate_files():
            for r in read_csv(path):
                sym=norm_symbol(r.get("symbol"))
                if not sym:continue
                key=f"{source}|{sym}|{str(r.get('direction') or '')}"
                last=self.last_snapshot.get(key)
                if last and (now.timestamp()-last)<SNAPSHOT_DEDUPE_SECONDS:
                    continue
                self.last_snapshot[key]=now.timestamp()
                snap=fingerprint(source,r,now)
                first_key=f"{sym}|{str(r.get('direction') or '')}"
                if first_key not in self.first_candidate:
                    self.first_candidate[first_key]=now.isoformat()
                first=parse_dt(self.first_candidate[first_key])
                snap["signal_age_minutes"]=round((now-first).total_seconds()/60,2) if first else 0
                snapshots.append(snap)
                events.append({
                    "event_time":now.isoformat(),"trading_date":now.date().isoformat(),
                    "event_type":source,"symbol":sym,
                    "direction":str(r.get("direction") or ""),
                    "status":str(r.get("paper_trade_status") or ""),
                    "reason":str(r.get("rejection_reason") or ""),
                    "details_json":json.dumps(snap,ensure_ascii=False),
                })
        append_csv(SNAPSHOTS_CSV,snapshots)
        return events

    def capture_leadership(self, now: datetime) -> list[dict[str, Any]]:
        events=[]
        for label,csvp,jsonp in (
            ("LEADERSHIP_V6",V6_CSV,V6_JSON),
            ("LEADERSHIP_V64",V64_CSV,V64_JSON),
        ):
            rows=read_csv(csvp)
            if not rows: rows=json_rows(read_json(jsonp))
            for r in rows:
                sym=norm_symbol(r.get("symbol"))
                if not sym:continue
                qualifies = (
                    boo(r.get("qualified_shadow"))
                    or boo(r.get("leadership_fast_track"))
                    or str(r.get("state") or "").upper() in {"RAPID_RISER","FAST_BREAKOUT","IMPROVING"}
                )
                if not qualifies:continue
                key=f"{label}|{sym}|{str(r.get('direction') or '')}"
                last=self.last_snapshot.get(key)
                if last and now.timestamp()-last<SNAPSHOT_DEDUPE_SECONDS:continue
                self.last_snapshot[key]=now.timestamp()
                snap=fingerprint(label,r,now)
                snap["rank"]=r.get("rank","")
                snap["rank_change_5m"]=r.get("rank_change_5m","")
                snap["rank_change_10m"]=r.get("rank_change_10m","")
                snap["move_change_3m_pct"]=r.get("move_change_3m_pct","")
                snap["move_change_5m_pct"]=r.get("move_change_5m_pct","")
                snap["move_change_10m_pct"]=r.get("move_change_10m_pct","")
                snap["leadership_state"]=r.get("state") or r.get("leg_state") or ""
                snap["leg_state"]=r.get("leg_state") or ""
                append_csv(SNAPSHOTS_CSV,[snap])
                events.append({
                    "event_time":now.isoformat(),"trading_date":now.date().isoformat(),
                    "event_type":label,"symbol":sym,
                    "direction":str(r.get("direction") or ""),
                    "status":str(snap.get("leadership_state") or ""),
                    "reason":"","details_json":json.dumps(snap,ensure_ascii=False),
                })
        return events

    def capture_log(self) -> list[dict[str, Any]]:
        if not SCANNER_LOG.exists():
            return []
        events=[]
        try:
            size=SCANNER_LOG.stat().st_size
            if self.log_offset>size:self.log_offset=0
            with SCANNER_LOG.open("r",encoding="utf-8",errors="ignore") as h:
                h.seek(self.log_offset)
                text=h.read()
                self.log_offset=h.tell()
        except Exception:
            return []
        patterns=("PAPER conversion audit","OPTION_EXPIRY_FALLBACK","SAFETY_BLOCKED","OPTION_PLAN_FAILED")
        for line in text.splitlines():
            if not any(p in line for p in patterns):
                continue
            mt=re.match(r"^(20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",line)
            ts=parse_dt(mt.group(1)) if mt else now_ist()
            sm=re.search(r"\bsymbol=([A-Z0-9&\-]+)",line)
            sym=sm.group(1) if sm else ""
            et="SCANNER_DECISION"
            if "PAPER conversion audit" in line:et="PAPER_CONVERSION_AUDIT"
            elif "OPTION_EXPIRY_FALLBACK" in line:et="OPTION_EXPIRY_FALLBACK"
            events.append({
                "event_time":ts.isoformat(),"trading_date":ts.date().isoformat(),
                "event_type":et,"symbol":sym,"direction":"",
                "status":"","reason":line[-1200:],"details_json":"",
            })
        return events

    def paper_rows(self) -> list[dict[str, Any]]:
        rows=read_csv(PAPER_CSV)
        if rows:return rows
        return json_rows(read_json(PAPER_JSON))

    def capture_paper(self, now: datetime) -> list[dict[str, Any]]:
        events=[]
        market=market_map()
        for r in self.paper_rows():
            tid=str(r.get("paper_trade_id") or r.get("trade_id") or r.get("id") or "")
            sym=norm_symbol(r.get("symbol"))
            if not tid or not sym:continue
            status=str(r.get("status") or "").upper()
            direction=str(r.get("direction") or "").upper()
            entry_dt=parse_dt(r.get("entry_time"))
            if tid not in self.paper_seen:
                self.paper_seen.add(tid)
                m=market.get(sym,{})
                ul=underlying_ltp(m)
                self.trade_track[tid]={
                    "symbol":sym,"direction":direction,
                    "entry_time":entry_dt.isoformat() if entry_dt else now.isoformat(),
                    "entry_underlying":ul,
                    "horizons_done":[],
                    "last_status":status,
                }
                events.append({
                    "event_time":(entry_dt or now).isoformat(),
                    "trading_date":(entry_dt or now).date().isoformat(),
                    "event_type":"PAPER_ENTRY","symbol":sym,"direction":direction,
                    "status":status,"reason":str(r.get("entry_reason") or ""),
                    "details_json":json.dumps(dict(r),ensure_ascii=False),
                })
            track=self.trade_track.get(tid,{})
            old=track.get("last_status","")
            if status=="CLOSED" and old!="CLOSED":
                xdt=parse_dt(r.get("exit_time")) or now
                events.append({
                    "event_time":xdt.isoformat(),"trading_date":xdt.date().isoformat(),
                    "event_type":"PAPER_EXIT","symbol":sym,"direction":direction,
                    "status":"CLOSED","reason":str(r.get("exit_reason") or ""),
                    "details_json":json.dumps(dict(r),ensure_ascii=False),
                })
            if track is not None:
                track["last_status"]=status
        return events

    def capture_trade_paths(self, now: datetime) -> None:
        market=market_map()
        rows=[]
        for tid,t in list(self.trade_track.items()):
            edt=parse_dt(t.get("entry_time"))
            if not edt:continue
            sym=t.get("symbol","");direction=t.get("direction","")
            current=underlying_ltp(market.get(sym,{}))
            entry=num(t.get("entry_underlying"))
            if entry<=0 and current>0:
                # First available underlying observation becomes the reference.
                t["entry_underlying"]=current;entry=current
            done=set(int(x) for x in t.get("horizons_done",[]))
            for mins in PATH_HORIZONS:
                if mins in done:continue
                if now < edt+timedelta(minutes=mins):continue
                move=directional_move(direction,entry,current)
                rows.append({
                    "captured_at":now.isoformat(),"trading_date":edt.date().isoformat(),
                    "trade_id":tid,"symbol":sym,"direction":direction,
                    "entry_time":edt.isoformat(),"horizon_minutes":mins,
                    "entry_underlying":entry,"observed_underlying":current,
                    "directional_move_pct":move if move is not None else "",
                })
                done.add(mins)
            t["horizons_done"]=sorted(done)
        append_csv(TRADE_PATH_CSV,rows)

    def cycle(self):
        now=now_ist()
        events=[]
        events.extend(self.capture_candidates(now))
        events.extend(self.capture_leadership(now))
        events.extend(self.capture_log())
        events.extend(self.capture_paper(now))
        append_csv(EVENTS_CSV,events)
        self.capture_trade_paths(now)
        self._save_state()
        summary={
            "updated_at":now.isoformat(),
            "events_this_cycle":len(events),
            "tracked_trades":len(self.trade_track),
            "candidate_snapshot_file":str(SNAPSHOTS_CSV),
            "events_file":str(EVENTS_CSV),
            "trade_path_file":str(TRADE_PATH_CSV),
            "zero_dhan_calls":True,
            "strategy_changes":False,
        }
        atomic_text(LATEST_JSON,json.dumps(summary,indent=2))
        return summary

    def run_loop(self, interval=POLL_SECONDS):
        print("="*118)
        print("APlus Decision Evidence Recorder V1")
        print("OBSERVATION ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES")
        print("="*118)
        while True:
            try:
                s=self.cycle()
                print(f'{now_ist().strftime("%H:%M:%S")} recorder events={s["events_this_cycle"]} tracked_trades={s["tracked_trades"]}')
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"Recorder cycle failed non-fatally: {type(e).__name__}: {e}")
            time.sleep(max(5,int(interval)))

if __name__=="__main__":
    Recorder().run_loop()
