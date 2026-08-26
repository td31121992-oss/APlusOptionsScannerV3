# APLUS_GLOBAL_STOCK_SEARCH_V1_V2
from __future__ import annotations
import csv, json, math, os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
REPORTS=ROOT/"data"/"reports"
CHART_BASE=ROOT/"data"/"chart_history"
OPEN_MOVE_BASE=ROOT/"data"/"open_move_pattern_history"
RANK_BASE=ROOT/"data"/"research"/"top_bottom_from_open"
IST=ZoneInfo("Asia/Kolkata")
HOST="127.0.0.1"
PORT=int(os.getenv("APLUS_DASHBOARD_V2_PORT","8772"))
MARKET_WATCH=REPORTS/"fno_market_watch_latest.json"
MOVEMENT=REPORTS/"intraday_movement_latest.json"
OPEN_MOVE_LATEST=REPORTS/"open_move_patterns_latest.json"
PAPER_TRADES=REPORTS/"paper_trades_latest.json"
TOP_BOTTOM=REPORTS/"top_bottom_from_open_latest.json"

def _load_json(path):
    try:return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:return {}

def _f(v,d=0.0):
    try:
        x=float(v); return x if math.isfinite(x) else d
    except Exception:return d

def _rows(obj,*keys):
    if isinstance(obj,list):return [dict(x) for x in obj if isinstance(x,dict)]
    if not isinstance(obj,dict):return []
    for k in keys:
        v=obj.get(k)
        if isinstance(v,list):return [dict(x) for x in v if isinstance(x,dict)]
    return []

def _today():return datetime.now(IST).date().isoformat()
def _market_rows():return _rows(_load_json(MARKET_WATCH),"rows","stocks","data")
def _movement_rows():
    o=_load_json(MOVEMENT)
    for k in ("candidates","entry_ready","analysed","rows"):
        r=_rows(o,k)
        if r:return r
    return []
def _paper_rows():return _rows(_load_json(PAPER_TRADES),"paper_trades","trades","rows")
def _latest(rows):
    d={}
    for r in rows:
        s=str(r.get("symbol") or "").upper()
        if s:d[s]=r
    return d

def _open_map():
    o=_load_json(OPEN_MOVE_LATEST);d={}
    for k in ("idea_progressive_hits","kaynes_reversal_hits"):
        for r in _rows(o,k):
            s=str(r.get("symbol") or "").upper()
            if s:d.setdefault(s,{}).update(r)
    return d

def _rank_maps():
    o=_load_json(TOP_BOTTOM)
    return ({str(x.get("symbol") or "").upper():x for x in _rows(o,"current_top_from_open")},
            {str(x.get("symbol") or "").upper():x for x in _rows(o,"current_bottom_from_open")})

def _chart_rows(day,symbol):
    p=CHART_BASE/day/"market_watch_1m.csv"
    if not p.exists():return []
    try:
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            return [r for r in csv.DictReader(f) if str(r.get("symbol") or "").upper()==symbol]
    except Exception:return []

def _pattern_rows(day,symbol):
    p=OPEN_MOVE_BASE/day/"open_move_patterns.csv"
    if not p.exists():return []
    try:
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            return [r for r in csv.DictReader(f) if str(r.get("symbol") or "").upper()==symbol]
    except Exception:return []

def _rank_events(day,symbol):
    return _rows(_load_json(RANK_BASE/day/"stocks"/f"{symbol}.json"),"events")

def _trade_events(symbol):
    out=[]
    for t in _paper_rows():
        if str(t.get("symbol") or "").upper()!=symbol:continue
        out.append({"entry_time":t.get("entry_time",""),"exit_time":t.get("exit_time",""),"direction":t.get("direction") or t.get("side") or "","status":t.get("status",""),"pnl":_f(t.get("net_pnl",t.get("pnl"))),"exit_reason":t.get("exit_reason",""),"setup":t.get("setup_family",t.get("setup",""))})
    return out

def _tech(symbol):
    m=_latest(_market_rows()).get(symbol,{})
    c=_latest(_movement_rows()).get(symbol,{})
    p=_open_map().get(symbol,{})
    top,bot=_rank_maps()
    def first(*names,default=None):
        for n in names:
            for src in (c,m,p):
                if n in src and src.get(n) not in (None,""):return src.get(n)
        return default
    move=_f(first("move_from_0915_open_percent","move_from_open_percent","from_open_pct"))
    rp=_f(first("range_position_percent","range_pos_pct"),50)
    if 0<=rp<=1:rp*=100
    direction=str(first("direction","pattern_direction",default="") or "").upper() or ("BULLISH" if move>.15 else "BEARISH" if move<-.15 else "NEUTRAL")
    checks=[];bull=0;bear=0
    def add(label,state,value):
        nonlocal bull,bear
        if state=="BULL":bull+=1
        elif state=="BEAR":bear+=1
        checks.append({"label":label,"state":state,"value":value})
    vd=_f(first("vwap_distance_percent","vwap_distance_pct"));add("VWAP","BULL" if vd>.05 else "BEAR" if vd<-.05 else "NEUTRAL",f"{vd:+.2f}%")
    m5=_f(first("recent_move_5m_percent","recent_move_5m_pct"));add("5m momentum","BULL" if m5>.08 else "BEAR" if m5<-.08 else "NEUTRAL",f"{m5:+.2f}%")
    m10=_f(first("recent_move_10m_percent","recent_move_10m_pct"));add("10m momentum","BULL" if m10>.15 else "BEAR" if m10<-.15 else "NEUTRAL",f"{m10:+.2f}%")
    add("Range position","BULL" if rp>=70 else "BEAR" if rp<=30 else "NEUTRAL",f"{rp:.0f}%")
    ret=_f(first("trend_retention_percent","trend_retention_pct"));add("Trend retention","BULL" if direction=="BULLISH" and ret>=68 else "BEAR" if direction=="BEARISH" and ret>=68 else "NEUTRAL",f"{ret:.0f}%")
    fh=bool(first("fresh_15m_high","fresh_day_high","opening_range_breakout",default=False));fl=bool(first("fresh_15m_low","fresh_day_low",default=False));add("Fresh break","BULL" if fh else "BEAR" if fl else "NEUTRAL","YES" if fh or fl else "NO")
    return {"symbol":symbol,"sector":first("sector",default=""),"ltp":_f(first("ltp")),"open_0915":_f(first("open_0915","open")),"prev_close":_f(first("previous_close","prev_close")),"day_high":_f(first("day_high","high")),"day_low":_f(first("day_low","low")),"from_open_pct":move,"gap_pct":_f(first("gap_pct","gap_percent")),"range_position_pct":rp,"vwap":_f(first("vwap","average_price")),"vwap_distance_pct":vd,"quality":_f(first("trade_quality_score","quality_score")),"clean":_f(first("clean_trend_score")),"alignment":_f(first("trend_alignment_score")),"rvol":_f(first("relative_volume","relative_participation")),"m5":m5,"m10":m10,"m15":_f(first("recent_move_15m_percent","recent_move_15m_pct")),"direction":direction,"paper_status":str(first("paper_trade_status",default="") or ""),"rejection_reason":str(first("rejection_reason",default="") or ""),"progressive":bool(first("idea_progressive",default=False)),"reversal":bool(first("kaynes_reversal",default=False)),"progressive_first":str(first("progressive_first_time",default="") or ""),"reversal_first":str(first("reversal_first_time",default="") or ""),"top_rank":top.get(symbol,{}).get("rank",""),"bottom_rank":bot.get(symbol,{}).get("rank",""),"bullish_count":bull,"bearish_count":bear,"checks":checks}

def _symbols_payload():
    cand=_latest(_movement_rows());pat=_open_map();top,bot=_rank_maps();out=[]
    for r in _market_rows():
        s=str(r.get("symbol") or "").upper()
        if not s:continue
        c=cand.get(s,{});p=pat.get(s,{})
        out.append({"symbol":s,"sector":r.get("sector",""),"ltp":_f(r.get("ltp")),"from_open_pct":_f(r.get("from_open_pct",r.get("move_from_open_percent"))),"direction":r.get("direction",""),"quality":_f(c.get("trade_quality_score")),"paper_status":c.get("paper_trade_status",""),"progressive":bool(p.get("idea_progressive")),"reversal":bool(p.get("kaynes_reversal")),"top_rank":top.get(s,{}).get("rank",""),"bottom_rank":bot.get(s,{}).get("rank","")})
    out.sort(key=lambda x:x["from_open_pct"],reverse=True)
    return {"generated_at":_load_json(MARKET_WATCH).get("generated_at",""),"day":_today(),"count":len(out),"rows":out}


# =====================================================================
# APLUS DASHBOARD V2.1 — PRICE-HISTORY TECHNICAL INTELLIGENCE
# Derived ONLY from existing local minute history. ZERO Dhan calls.
# =====================================================================
def _pct(a,b):
    return ((a-b)/b*100.0) if b else 0.0

def _history_intelligence(rows, base_tech):
    tech=dict(base_tech or {})
    if not rows:
        tech.update({
            "history_ready":False,
            "history_points":0,
            "movement_start_time":"",
            "trend_structure":"NO_HISTORY",
            "progressive_derived":False,
            "reacceleration_derived":False,
            "pullback_depth_pct":0.0,
            "trend_retention_derived_pct":0.0,
            "fresh_break_derived":False,
        })
        return tech

    pts=[]
    for r in rows:
        ltp=_f(r.get("ltp"))
        if ltp<=0: continue
        pts.append({
            "time":str(r.get("minute") or ""),
            "ltp":ltp,
            "from_open":_f(r.get("from_open_pct")),
            "day_high":_f(r.get("day_high")),
            "day_low":_f(r.get("day_low")),
        })
    if not pts:
        tech["history_ready"]=False
        return tech

    prices=[x["ltp"] for x in pts]
    moves=[x["from_open"] for x in pts]
    last=prices[-1]
    current_move=moves[-1]
    direction="BULLISH" if current_move>0.15 else ("BEARISH" if current_move<-0.15 else "NEUTRAL")
    tech["direction"]=direction

    def mom(n):
        if len(prices)<=n: return 0.0
        return _pct(prices[-1], prices[-1-n])

    m5,m10,m15=mom(5),mom(10),mom(15)
    tech["m5"]=m5
    tech["m10"]=m10
    tech["m15"]=m15

    session_high=max(prices)
    session_low=min(prices)
    spread=session_high-session_low
    rp=((last-session_low)/spread*100.0) if spread>0 else 50.0
    tech["range_position_pct"]=max(0.0,min(100.0,rp))

    max_move=max(moves)
    min_move=min(moves)
    if direction=="BULLISH" and max_move>0:
        retention=max(0.0,min(100.0,current_move/max_move*100.0))
        pullback=max(0.0,max_move-current_move)
        favorable=max_move
    elif direction=="BEARISH" and min_move<0:
        retention=max(0.0,min(100.0,abs(current_move)/abs(min_move)*100.0))
        pullback=max(0.0,abs(min_move)-abs(current_move))
        favorable=abs(min_move)
    else:
        retention=0.0; pullback=0.0; favorable=abs(current_move)
    tech["trend_retention_derived_pct"]=retention
    tech["pullback_depth_pct"]=pullback
    tech["max_favorable_from_open_pct"]=favorable

    # Structure from the last 15 one-minute closes.
    tail=prices[-16:]
    deltas=[tail[i]-tail[i-1] for i in range(1,len(tail))]
    up_ratio=(sum(1 for d in deltas if d>0)/len(deltas)*100.0) if deltas else 50.0
    down_ratio=(sum(1 for d in deltas if d<0)/len(deltas)*100.0) if deltas else 50.0
    if direction=="BULLISH":
        structure_ratio=up_ratio
        structure="HIGHER_CLOSE_SEQUENCE" if up_ratio>=60 else ("MIXED" if up_ratio>=45 else "WEAKENING")
    elif direction=="BEARISH":
        structure_ratio=down_ratio
        structure="LOWER_CLOSE_SEQUENCE" if down_ratio>=60 else ("MIXED" if down_ratio>=45 else "WEAKENING")
    else:
        structure_ratio=max(up_ratio,down_ratio)
        structure="SIDEWAYS"
    tech["structure_ratio_pct"]=structure_ratio
    tech["trend_structure"]=structure

    near_high = last >= session_high*0.9985
    near_low = last <= session_low*1.0015
    fresh_break=(direction=="BULLISH" and near_high) or (direction=="BEARISH" and near_low)
    tech["fresh_break_derived"]=fresh_break

    # Reacceleration: latest 5m impulse stronger than preceding 5m impulse
    # and aligned to the session direction.
    prev5=0.0
    if len(prices)>10:
        prev5=_pct(prices[-6],prices[-11])
    if direction=="BULLISH":
        reaccel=(m5>0.18 and m5>prev5+0.05)
    elif direction=="BEARISH":
        reaccel=(m5<-0.18 and m5<prev5-0.05)
    else:
        reaccel=False
    tech["reacceleration_derived"]=reaccel

    progressive=(
        direction=="BULLISH" and current_move>=1.0 and retention>=72 and
        tech["range_position_pct"]>=68 and structure_ratio>=48
    ) or (
        direction=="BEARISH" and current_move<=-1.0 and retention>=72 and
        tech["range_position_pct"]<=32 and structure_ratio>=48
    )
    tech["progressive_derived"]=progressive

    # Earliest point where a move became technically meaningful:
    # >=0.45% from open + aligned 5m impulse >=0.20% + reasonable retention.
    start=""
    start_move=0.0
    for i in range(5,len(pts)):
        mv=moves[i]
        m5i=_pct(prices[i],prices[i-5])
        prefix=moves[:i+1]
        if mv>=0.45:
            fav=max(prefix)
            reti=(mv/fav*100.0) if fav>0 else 0
            if m5i>=0.20 and reti>=65:
                start=pts[i]["time"];start_move=mv;break
        elif mv<=-0.45:
            fav=min(prefix)
            reti=(abs(mv)/abs(fav)*100.0) if fav<0 else 0
            if m5i<=-0.20 and reti>=65:
                start=pts[i]["time"];start_move=mv;break
    tech["movement_start_time"]=start
    tech["movement_start_move_pct"]=start_move
    tech["history_ready"]=True
    tech["history_points"]=len(pts)

    # Current VWAP can only be shown if a local source actually records it.
    # Do not fabricate VWAP from price-only history.
    if _f(tech.get("vwap"))<=0:
        tech["vwap_available"]=False
        tech["vwap"]=0.0
        tech["vwap_distance_pct"]=0.0
    else:
        tech["vwap_available"]=True

    # Rebuild right-panel checks from real history-derived values.
    checks=[];bull=0;bear=0
    def add(label,state,value):
        nonlocal bull,bear
        if state=="BULL": bull+=1
        elif state=="BEAR": bear+=1
        checks.append({"label":label,"state":state,"value":value})

    if tech.get("vwap_available"):
        vd=_f(tech.get("vwap_distance_pct"))
        add("VWAP","BULL" if vd>.05 else ("BEAR" if vd<-.05 else "NEUTRAL"),f"{vd:+.2f}%")
    else:
        add("VWAP","NEUTRAL","N/A")

    add("5m momentum","BULL" if m5>.08 else ("BEAR" if m5<-.08 else "NEUTRAL"),f"{m5:+.2f}%")
    add("10m momentum","BULL" if m10>.15 else ("BEAR" if m10<-.15 else "NEUTRAL"),f"{m10:+.2f}%")
    add("Range position","BULL" if rp>=70 else ("BEAR" if rp<=30 else "NEUTRAL"),f"{rp:.0f}%")
    add("Trend retention",
        "BULL" if direction=="BULLISH" and retention>=70 else
        ("BEAR" if direction=="BEARISH" and retention>=70 else "NEUTRAL"),
        f"{retention:.0f}%")
    add("Price structure",
        "BULL" if direction=="BULLISH" and structure_ratio>=55 else
        ("BEAR" if direction=="BEARISH" and structure_ratio>=55 else "NEUTRAL"),
        f"{structure_ratio:.0f}%")
    add("Fresh break",
        "BULL" if fresh_break and direction=="BULLISH" else
        ("BEAR" if fresh_break and direction=="BEARISH" else "NEUTRAL"),
        "YES" if fresh_break else "NO")
    add("Reacceleration",
        "BULL" if reaccel and direction=="BULLISH" else
        ("BEAR" if reaccel and direction=="BEARISH" else "NEUTRAL"),
        "YES" if reaccel else "NO")

    tech["checks"]=checks
    tech["bullish_count"]=bull
    tech["bearish_count"]=bear
    tech["technical_total_checks"]=len(checks)
    return tech


def _stock_payload(day,symbol):
    symbol=symbol.upper().strip();chart=_chart_rows(day,symbol);tech=_history_intelligence(chart,_tech(symbol));patterns=_pattern_rows(day,symbol);ranks=_rank_events(day,symbol);trades=_trade_events(symbol)
    points=[{"time":r.get("minute",""),"ltp":_f(r.get("ltp")),"from_open_pct":_f(r.get("from_open_pct")),"day_high":_f(r.get("day_high")),"day_low":_f(r.get("day_low")),"range_position_pct":_f(r.get("range_position_pct"))} for r in chart]
    timeline=[]
    for r in patterns:
        if str(r.get("idea_progressive","")).lower() in ("true","1","yes"):timeline.append({"time":r.get("timestamp",""),"type":"PROGRESSIVE","detail":f"Move {_f(r.get('move_from_open_pct')):+.2f}%"})
        if str(r.get("kaynes_reversal","")).lower() in ("true","1","yes"):timeline.append({"time":r.get("timestamp",""),"type":"REVERSAL","detail":f"Recovery {_f(r.get('recovery_from_extreme_pct')):+.2f}%"})
    for e in ranks:
        if e.get("event") in ("ENTER","RE_ENTER"):timeline.append({"time":e.get("timestamp",""),"type":e.get("side","RANK"),"detail":f"Rank {e.get('rank','')}"})
    for t in trades:
        if t.get("entry_time"):timeline.append({"time":t["entry_time"],"type":"TRADE_ENTRY","detail":f"{t['direction']} • {t['setup']}"})
        if t.get("exit_time"):timeline.append({"time":t["exit_time"],"type":"TRADE_EXIT","detail":f"PnL ₹{t['pnl']:,.0f} • {t['exit_reason']}"})
    timeline.sort(key=lambda x:str(x.get("time") or ""))
    return {"day":day,"symbol":symbol,"tech":tech,"points":points,"timeline":timeline[-120:],"trades":trades}

HTML = '<!doctype html>\n<html>\n<head>\n<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>APlus Dashboard V2</title>\n<style>\n:root{--bg:#070b14;--panel:#0d1422;--panel2:#101a2c;--line:#202d45;--text:#edf4ff;--muted:#8293ad;--green:#1bd993;--red:#ff426f;--cyan:#28d7e5;--amber:#f4c95d}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif}\nheader{height:64px;padding:0 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;background:#09101d;position:sticky;top:0;z-index:5}\n.brand{font-size:21px;font-weight:900}.brand b{color:var(--green)}.small{font-size:11px;color:var(--muted)}.nav{display:flex;gap:6px}.nav button{border:1px solid var(--line);background:var(--panel);color:var(--muted);padding:8px 12px;border-radius:7px;font-weight:700}.nav button.active{color:var(--cyan);border-color:#1d6775}\n.shell{display:grid;grid-template-columns:300px minmax(600px,1fr) 350px;gap:10px;padding:10px}\n.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}.ph{padding:10px 12px;border-bottom:1px solid var(--line);font-size:12px;font-weight:800;color:#c6d6ef}\n.stockhead{padding:14px}.symbol{font-size:26px;font-weight:900}.price{font-size:26px;font-weight:800}.up{color:var(--green)}.down{color:var(--red)}.neutral{color:var(--muted)}\n.metrics{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line);margin-top:12px}.metric{background:var(--panel);padding:9px}.metric .k{font-size:10px;color:var(--muted);text-transform:uppercase}.metric .v{font-size:14px;font-weight:750;margin-top:3px}\n.range{height:5px;border-radius:5px;background:#192337;margin:8px 0;position:relative}.range span{position:absolute;top:-3px;width:11px;height:11px;border-radius:50%;background:var(--cyan)}\n.search{padding:8px}.search input{width:100%;background:#09101d;border:1px solid var(--line);color:var(--text);padding:9px;border-radius:7px}.stocklist{height:330px;overflow:auto}.srow{display:flex;justify-content:space-between;padding:7px 10px;border-top:1px solid #152038;cursor:pointer;font-size:12px}.srow:hover,.srow.sel{background:#142139}.badge{padding:2px 6px;border-radius:10px;background:#172238;font-size:9px;color:var(--cyan)}\n.chartbar{padding:10px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line)}.chartbox{height:470px;padding:6px}.chartbox svg{width:100%;height:100%}\n.tabs{display:flex;border-top:1px solid var(--line)}.tab{padding:10px 13px;font-size:11px;color:var(--muted);border-right:1px solid var(--line);cursor:pointer}.tab.active{color:var(--cyan);background:#101b2c}\n.tabbody{padding:12px;min-height:145px}.gridcards{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.card{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px}.card .k{font-size:10px;color:var(--muted)}.card .v{font-size:17px;font-weight:800;margin-top:4px}\n.gaugewrap{padding:14px}.gauge{height:14px;border-radius:12px;background:linear-gradient(90deg,var(--red),#5b6070,var(--green));position:relative}.needle{position:absolute;top:-6px;width:3px;height:26px;background:white}.trendlabel{text-align:center;font-weight:900;font-size:18px;margin:12px 0}\n.check{display:grid;grid-template-columns:1fr 60px 70px;padding:7px 10px;border-top:1px solid #172238;font-size:11px}.state{font-weight:800}.BULL{color:var(--green)}.BEAR{color:var(--red)}.NEUTRAL{color:var(--muted)}\n.scan{padding:8px 10px;border-top:1px solid #172238;display:flex;justify-content:space-between;font-size:11px}.scan.good{background:#13261e}\n.timeline{max-height:310px;overflow:auto}.event{display:grid;grid-template-columns:65px 105px 1fr;gap:7px;padding:7px 9px;border-top:1px solid #172238;font-size:10px}.etype{font-weight:800;color:var(--cyan)}\n.footer{padding:11px 16px;border-top:1px solid var(--line);font-size:10px;color:var(--muted);display:flex;justify-content:space-between}\n@media(max-width:1250px){.shell{grid-template-columns:260px 1fr}.rightcol{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:10px}}@media(max-width:800px){.shell{grid-template-columns:1fr}.rightcol{display:block}.chartbox{height:360px}.gridcards{grid-template-columns:1fr 1fr}}\n</style></head>\n<body>\n<header><div><div class="brand">APlus <b>Dashboard V2</b></div><div class="small">Research • Analyze • Execute • Improve</div></div><div class="nav"><button class="active">OVERVIEW</button><button onclick="location.href=\'http://127.0.0.1:8765/\'">P&amp;L V1</button><button onclick="location.href=\'http://127.0.0.1:8765/stock-charts\'">OLD CHARTS</button></div><div class="small" id="updated">Loading…</div></header>\n<div class="shell">\n<div>\n<div class="panel stockhead"><div class="small" id="sector">—</div><div class="symbol" id="symbol">—</div><div><span class="price" id="price">—</span> <span id="move" class="price" style="font-size:16px"></span></div><div class="range"><span id="rangeDot"></span></div><div class="metrics">\n<div class="metric"><div class="k">09:15 Open</div><div class="v" id="open">—</div></div><div class="metric"><div class="k">Prev Close</div><div class="v" id="prev">—</div></div><div class="metric"><div class="k">Day High</div><div class="v" id="high">—</div></div><div class="metric"><div class="k">Day Low</div><div class="v" id="low">—</div></div><div class="metric"><div class="k">VWAP</div><div class="v" id="vwap">—</div></div><div class="metric"><div class="k">Quality</div><div class="v" id="quality">—</div></div>\n</div></div>\n<div class="panel" style="margin-top:10px"><div class="ph">F&amp;O UNIVERSE • 208 STOCKS</div><div class="search"><input id="search" placeholder="Search symbol…"></div><div class="stocklist" id="stocklist"></div></div>\n</div>\n<div><div class="panel"><div class="chartbar"><div><b id="chartTitle">—</b><div class="small">1-minute movement from 09:15 open • scanner markers</div></div><div class="small" id="pointCount">—</div></div><div class="chartbox" id="chart"></div><div class="tabs"><div class="tab active" data-tab="overview">OVERVIEW</div><div class="tab" data-tab="dna">SCANNER DNA</div><div class="tab" data-tab="trades">TRADES</div><div class="tab" data-tab="forensic">FORENSIC</div></div><div class="tabbody" id="tabbody"></div></div></div>\n<div class="rightcol"><div class="panel"><div class="ph">STOCK TREND</div><div class="gaugewrap"><div class="gauge"><div class="needle" id="needle"></div></div><div class="trendlabel" id="trend">NEUTRAL</div><div class="small" style="text-align:center" id="counts"></div></div></div><div class="panel" style="margin-top:10px"><div class="ph">TECHNICAL STRUCTURE</div><div id="checks"></div></div><div class="panel" style="margin-top:10px"><div class="ph">INTRADAY SCANS / DNA</div><div id="scans"></div></div><div class="panel" style="margin-top:10px"><div class="ph">MOVEMENT TIMELINE</div><div class="timeline" id="timeline"></div></div></div>\n</div>\n<div class="footer"><span>Paper Trading • NSE F&amp;O • No Live Orders</span><span>APlus Dashboard V2 — standalone on port 8772</span></div>\n<script>\nconst $=x=>document.querySelector(x);let symbols=[],selected="",current=null,activeTab="overview";const fmt=n=>Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:2});const pc=n=>`${Number(n||0)>=0?"+":""}${Number(n||0).toFixed(2)}%`;function klass(n){return Number(n)>0?"up":Number(n)<0?"down":"neutral"}function timeOnly(s){if(!s)return "—";let m=String(s).match(/T(\\d\\d:\\d\\d)/);return m?m[1]:String(s).slice(0,5)}\nasync function loadSymbols(){let r=await fetch("/api/v2/symbols?ts="+Date.now()),j=await r.json();symbols=j.rows||[];$("#updated").textContent=`${j.day||""} • ${j.count||0} stocks`;renderList();if(!selected&&symbols.length){let idea=symbols.find(x=>x.symbol==="IDEA");selectStock((idea||symbols[0]).symbol)}}\nfunction renderList(){let q=$("#search").value.trim().toUpperCase();let arr=symbols.filter(x=>!q||x.symbol.includes(q));$("#stocklist").innerHTML=arr.map(x=>`<div class="srow ${x.symbol===selected?"sel":""}" onclick="selectStock(\'${x.symbol}\')"><span><b>${x.symbol}</b>${x.progressive?\' <span class="badge">PROG</span>\':\'\'}${x.reversal?\' <span class="badge">REV</span>\':\'\'}</span><span class="${klass(x.from_open_pct)}">${pc(x.from_open_pct)}</span></div>`).join("")}\nasync function selectStock(sym){selected=sym;renderList();let day=new Date().toISOString().slice(0,10);let r=await fetch(`/api/v2/stock?day=${day}&symbol=${encodeURIComponent(sym)}&ts=${Date.now()}`);current=await r.json();renderAll()}\nfunction renderAll(){let t=current.tech||{};$("#symbol").textContent=current.symbol;$("#sector").textContent=t.sector||"F&O Stock";$("#price").textContent=fmt(t.ltp);$("#move").textContent=pc(t.from_open_pct);$("#move").className="price "+klass(t.from_open_pct);$("#open").textContent=fmt(t.open_0915);$("#prev").textContent=fmt(t.prev_close);$("#high").textContent=fmt(t.day_high);$("#low").textContent=fmt(t.day_low);$("#vwap").textContent=t.vwap_available?fmt(t.vwap):"N/A";$("#quality").textContent=Number(t.quality||0)>0?Number(t.quality).toFixed(1):"N/A";$("#rangeDot").style.left=Math.max(0,Math.min(98,Number(t.range_position_pct||0)))+"%";$("#chartTitle").textContent=current.symbol+" • "+pc(t.from_open_pct);$("#pointCount").textContent=(current.points||[]).length+" minute points";renderChart();renderTrend();renderChecks();renderScans();renderTimeline();renderTab()}\nfunction renderTrend(){let t=current.tech||{},bu=t.bullish_count||0,be=t.bearish_count||0,total=Math.max(1,bu+be),score=(bu-be)/total,pos=50+score*42;$("#needle").style.left=pos+"%";let label=score>.22?"BULLISH":score<-.22?"BEARISH":"NEUTRAL";$("#trend").textContent=label;$("#trend").className="trendlabel "+(label==="BULLISH"?"up":label==="BEARISH"?"down":"neutral");$("#counts").textContent=`Bearish ${be} • Neutral ${Math.max(0,6-bu-be)} • Bullish ${bu}`}\nfunction renderChecks(){let t=current.tech||{};$("#checks").innerHTML=(t.checks||[]).map(x=>`<div class="check"><span>${x.label}</span><span class="state ${x.state}">${x.state}</span><span>${x.value}</span></div>`).join("")}\nfunction renderScans(){let t=current.tech||{},items=[["Progressive Move",t.progressive||t.progressive_derived],["Reacceleration",t.reacceleration_derived],["Movement Started",!!t.movement_start_time],["Top 5 From Open",!!t.top_rank],["Bottom 5 From Open",!!t.bottom_rank],["KAYNES Reversal",t.reversal],["Entry Ready",String(t.paper_status||"").includes("READY")],["VWAP Aligned",t.vwap_available&&((t.direction==="BULLISH"&&t.vwap_distance_pct>0)||(t.direction==="BEARISH"&&t.vwap_distance_pct<0))]];$("#scans").innerHTML=items.map(x=>`<div class="scan ${x[1]?"good":""}"><span>${x[0]}</span><b>${x[1]?"YES":"—"}</b></div>`).join("")}\nfunction renderTimeline(){let arr=(current.timeline||[]).slice(-24).reverse();$("#timeline").innerHTML=arr.length?arr.map(e=>`<div class="event"><span>${timeOnly(e.time)}</span><span class="etype">${e.type}</span><span>${e.detail}</span></div>`).join(""):\'<div class="small" style="padding:12px">No timeline events recorded yet.</div>\'}\nfunction renderChart(){let pts=current.points||[],box=$("#chart");if(!pts.length){box.innerHTML=\'<div class="small" style="padding:25px">No minute-history for this symbol/day yet.</div>\';return}let w=1000,h=450,l=55,r=18,top=20,b=36,vals=pts.map(x=>Number(x.from_open_pct||0)),mn=Math.min(...vals,0),mx=Math.max(...vals,0),pad=Math.max(.15,(mx-mn)*.12);mn-=pad;mx+=pad;let X=i=>l+(w-l-r)*(i/Math.max(1,pts.length-1)),Y=v=>(h-b)-(h-b-top)*((v-mn)/(mx-mn));let grids="",labels="";for(let i=0;i<5;i++){let y=top+(h-b-top)*i/4,v=mx-(mx-mn)*i/4;grids+=`<line x1="${l}" y1="${y}" x2="${w-r}" y2="${y}" stroke="#202d45"/><text x="5" y="${y+4}" fill="#8293ad" font-size="12">${v.toFixed(2)}%</text>`}for(let f of [0,.25,.5,.75,1]){let i=Math.round((pts.length-1)*f),x=X(i);labels+=`<text x="${x}" y="${h-9}" fill="#8293ad" font-size="11" text-anchor="middle">${pts[i].time||""}</text>`}let poly=vals.map((v,i)=>`${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" "),stroke=vals[vals.length-1]>=0?"#1bd993":"#ff426f",zero=Y(0);let marks="";for(let e of (current.timeline||[])){let tm=timeOnly(e.time),idx=pts.findIndex(p=>p.time===tm);if(idx<0)continue;let typ=e.type||"";if(!["PROGRESSIVE","REVERSAL","TRADE_ENTRY","TRADE_EXIT","TOP_FROM_OPEN","BOTTOM_FROM_OPEN"].includes(typ))continue;let y=Y(vals[idx]);marks+=`<circle cx="${X(idx)}" cy="${y}" r="5" fill="${typ===\'TRADE_ENTRY\'?\'#f4c95d\':typ===\'TRADE_EXIT\'?\'#ff426f\':\'#28d7e5\'}"><title>${typ} ${tm}</title></circle>`}box.innerHTML=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${grids}<line x1="${l}" y1="${zero}" x2="${w-r}" y2="${zero}" stroke="#64748b" stroke-dasharray="4 5"/><polyline points="${poly}" fill="none" stroke="${stroke}" stroke-width="3" vector-effect="non-scaling-stroke"/>${marks}${labels}</svg>`}\nfunction renderTab(){let t=current.tech||{},body=$("#tabbody");if(activeTab==="overview"){body.innerHTML=`<div class="gridcards"><div class="card"><div class="k">From open</div><div class="v ${klass(t.from_open_pct)}">${pc(t.from_open_pct)}</div></div><div class="card"><div class="k">5m momentum</div><div class="v ${klass(t.m5)}">${pc(t.m5)}</div></div><div class="card"><div class="k">10m momentum</div><div class="v ${klass(t.m10)}">${pc(t.m10)}</div></div><div class="card"><div class="k">Range position</div><div class="v">${Number(t.range_position_pct||0).toFixed(0)}%</div></div></div>`}else if(activeTab==="dna"){body.innerHTML=`<div class="gridcards"><div class="card"><div class="k">Quality</div><div class="v">${Number(t.quality||0).toFixed(1)}</div></div><div class="card"><div class="k">Clean trend</div><div class="v">${Number(t.clean||0).toFixed(1)}</div></div><div class="card"><div class="k">Alignment</div><div class="v">${Number(t.alignment||0).toFixed(1)}</div></div><div class="card"><div class="k">Relative volume</div><div class="v">${Number(t.rvol||0).toFixed(2)}</div></div></div>`}else if(activeTab==="trades"){let tr=current.trades||[];body.innerHTML=tr.length?tr.map(x=>`<div class="scan"><span><b>${x.direction}</b> ${timeOnly(x.entry_time)} → ${timeOnly(x.exit_time)}</span><span class="${klass(x.pnl)}">₹${fmt(x.pnl)}</span></div>`).join(""):\'<div class="small">No paper trade for this symbol today.</div>\'}else{let entry=(current.trades||[])[0];body.innerHTML=`<div class="gridcards"><div class="card"><div class="k">Movement start</div><div class="v">${t.movement_start_time||"—"}</div></div><div class="card"><div class="k">Observer first seen</div><div class="v">${timeOnly(t.progressive_first||t.reversal_first)}</div></div><div class="card"><div class="k">Actual trade entry</div><div class="v">${entry?timeOnly(entry.entry_time):"—"}</div></div><div class="card"><div class="k">Top/Bottom rank</div><div class="v">${t.top_rank?("#"+t.top_rank+" TOP"):t.bottom_rank?("#"+t.bottom_rank+" BOTTOM"):"—"}</div></div></div><div class="gridcards" style="margin-top:8px"><div class="card"><div class="k">Trend retention</div><div class="v">${Number(t.trend_retention_derived_pct||0).toFixed(0)}%</div></div><div class="card"><div class="k">Pullback from best</div><div class="v">${Number(t.pullback_depth_pct||0).toFixed(2)}%</div></div><div class="card"><div class="k">Structure</div><div class="v" style="font-size:12px">${t.trend_structure||"—"}</div></div><div class="card"><div class="k">Decision status</div><div class="v" style="font-size:12px">${t.paper_status||"—"}</div></div></div><div class="small" style="margin-top:10px">${t.rejection_reason||"History-derived intelligence uses only information available up to the selected minute/session."}</div>`}}\n$("#search").oninput=renderList;document.querySelectorAll(".tab").forEach(el=>el.onclick=()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));el.classList.add("active");activeTab=el.dataset.tab;renderTab()});loadSymbols();setInterval(()=>{loadSymbols();if(selected)selectStock(selected)},10000);\n</script></body></html>'

class Handler(BaseHTTPRequestHandler):
    def sendx(self,code,ctype,body):
        data=body if isinstance(body,bytes) else body.encode("utf-8")
        self.send_response(code);self.send_header("Content-Type",ctype);self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        p=urlparse(self.path);q={k:(v[0] if v else "") for k,v in parse_qs(p.query).items()}
        if p.path=="/api/v2/symbols":self.sendx(200,"application/json",json.dumps(_symbols_payload(),default=str));return
        if p.path=="/api/v2/stock":self.sendx(200,"application/json",json.dumps(_stock_payload(q.get("day") or _today(),q.get("symbol") or ""),default=str));return
        if p.path in ("/","/dashboard-v2"):self.sendx(200,"text/html; charset=utf-8",HTML);return
        self.sendx(404,"text/plain; charset=utf-8","Not found")
    def log_message(self,fmt,*args):return

def main():
    print("="*88);print("APlus Dashboard V2 - STANDALONE");print("Existing dashboard remains untouched on port 8765.");print(f"Open: http://{HOST}:{PORT}");print("="*88)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()

if __name__=="__main__":main()
