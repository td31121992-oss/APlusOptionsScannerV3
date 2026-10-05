from __future__ import annotations
import json,re
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parent
NEWS_DIR=ROOT/"data"/"news_intelligence"; EVENTS_PATH=NEWS_DIR/"events.jsonl"
IMPACT_ORDER={"VERY HIGH":4,"HIGH":3,"MEDIUM":2,"LOW":1,"UNKNOWN":0}
def _parse_time(v:Any)->datetime|None:
    if not isinstance(v,str) or not v.strip(): return None
    try:
        d=datetime.fromisoformat(v.strip().replace("Z","+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except ValueError:return None
def _text(v:Any)->str:return str(v or "").strip()
def _symbols(e):
    v=e.get("symbols") or e.get("symbol") or []
    if isinstance(v,str):v=re.split(r"[,;|\s]+",v)
    return {str(x).strip().upper() for x in v if str(x).strip()}
def _normalise(e):
    x=dict(e);x["symbol"]=_text(x.get("symbol")).upper();x["symbols"]=sorted(_symbols(x))
    x["title"]=_text(x.get("title") or x.get("headline"));x["summary"]=_text(x.get("summary") or x.get("description"))
    x["direction"]=_text(x.get("direction") or "NEUTRAL").upper();x["impact"]=_text(x.get("impact") or "UNKNOWN").upper()
    x["source_type"]=_text(x.get("source_type") or x.get("source") or "UNKNOWN");x["source_url"]=_text(x.get("source_url") or x.get("url"))
    x["published_at"]=_text(x.get("published_at") or x.get("timestamp"))
    try:x["confidence"]=max(0,min(1,float(x.get("confidence") or 0)))
    except (TypeError,ValueError):x["confidence"]=0.0
    return x
def load_events(path=EVENTS_PATH):
    if not path.is_file():return []
    out=[]
    try:
        for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
            if line.strip():
                try:
                    x=json.loads(line)
                    if isinstance(x,dict):out.append(_normalise(x))
                except json.JSONDecodeError:pass
    except OSError:pass
    return out
def _relevant(e,symbol):
    s=symbol.strip().upper()
    if s in _symbols(e):return True
    blob=" ".join((_text(e.get("title")),_text(e.get("summary")),_text(e.get("company")))).upper()
    return re.search(rf"\b{re.escape(s)}\b",blob) is not None
def news_context(symbol,*,as_of=None,max_age_hours=72,limit=8):
    s=symbol.strip().upper()
    if not s:return {"ok":False,"data_status":"UNAVAILABLE","symbol":"","events":[],"summary":"Symbol is required.","read_only":True}
    ref=(as_of or datetime.now(timezone.utc)).astimezone(timezone.utc);matched=[]
    for e in load_events():
        if not _relevant(e,s):continue
        t=_parse_time(e.get("published_at"))
        if t is None or t>ref:continue
        age=(ref-t).total_seconds()/3600
        if 0<=age<=max(0,float(max_age_hours)):
            x=dict(e);x["age_hours"]=round(age,2);matched.append(x)
    matched.sort(key=lambda x:(IMPACT_ORDER.get(_text(x.get("impact")).upper(),0),float(x.get("confidence") or 0),-float(x.get("age_hours") or 0)),reverse=True)
    matched=matched[:max(1,int(limit))]
    counts={k:0 for k in ("BULLISH","BEARISH","NEUTRAL","MIXED")}
    for e in matched:
        if e.get("direction") in counts:counts[e["direction"]]+=1
    return {"ok":True,"data_status":"AVAILABLE" if matched else "NO_MATCH","symbol":s,"lookback_hours":max_age_hours,"events":matched,"direction_counts":counts,"summary":f"{len(matched)} relevant news/event item(s)." if matched else "No timestamped local news/event found.","read_only":True,"trading_engine_untouched":True}
def write_jsonl(events,path=EVENTS_PATH):
    path.parent.mkdir(parents=True,exist_ok=True);n=0
    with path.open("a",encoding="utf-8") as f:
        for e in events:
            x=_normalise(e)
            if x.get("event_id") and x.get("title") and x.get("published_at"):
                f.write(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n");n+=1
    return n
