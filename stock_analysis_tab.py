from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
CHART_BASE = ROOT / "data" / "chart_history"

CANDIDATE_FILES = (
    "intraday_movement_candidates.csv",
    "opening_momentum_candidates.csv",
    "intraday_entry_ready.csv",
    "intraday_fresh_movement.csv",
    "intraday_wait_for_pullback.csv",
)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _read_market_watch() -> dict[str, Any]:
    path = REPORTS / "fno_market_watch_latest.json"
    if not path.is_file():
        return {"generated_at": "", "rows": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"generated_at": "", "rows": []}
    except Exception:
        return {"generated_at": "", "rows": []}


def _market_row(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    payload = _read_market_watch()
    for row in payload.get("rows", []):
        if str(row.get("symbol") or "").upper() == symbol:
            return dict(row)
    return {}


def _latest_candidate(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    best: dict[str, Any] = {}
    best_mtime = -1.0
    for name in CANDIDATE_FILES:
        path = REPORTS / name
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        for row in _read_csv(path):
            if str(row.get("symbol") or "").upper() != symbol:
                continue
            if not best or mtime >= best_mtime:
                best = dict(row)
                best["_source_file"] = name
                best_mtime = mtime
    return best


def _safe_day(day: str) -> str:
    value = str(day or "").strip()
    try:
        from datetime import date
        parsed = date.fromisoformat(value)
        return parsed.isoformat()
    except ValueError:
        return ""


def _load_points(day: str, symbol: str) -> list[dict[str, Any]]:
    safe_day = _safe_day(day)
    if not safe_day:
        return []
    path = CHART_BASE / safe_day / "market_watch_1m.csv"
    rows = _read_csv(path)
    symbol = symbol.strip().upper()
    out = []
    for row in rows:
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        out.append({
            "time": str(row.get("minute") or ""),
            "ltp": _f(row.get("ltp")),
            "from_open_pct": _f(row.get("from_open_pct")),
            "day_high": _f(row.get("day_high")),
            "day_low": _f(row.get("day_low")),
            "range_position_pct": _f(row.get("range_position_pct")),
        })
    return out


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    value = values[0]
    for x in values[1:]:
        value = alpha * x + (1.0 - alpha) * value
    return value


def _rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains = []
    losses = []
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        delta = b - a
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss <= 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _move(values: list[float], minutes: int) -> float:
    if len(values) <= minutes:
        return 0.0
    base = values[-minutes - 1]
    return ((values[-1] - base) / base * 100.0) if base else 0.0


def _technical(points: list[dict[str, Any]], market: dict[str, Any]) -> dict[str, Any]:
    prices = [x["ltp"] for x in points if x["ltp"] > 0]
    return {
        "ema9_1m": round(_ema(prices, 9), 2) if prices else 0.0,
        "ema20_1m": round(_ema(prices, 20), 2) if prices else 0.0,
        "ema50_1m": round(_ema(prices, 50), 2) if prices else 0.0,
        "rsi14_1m": round(_rsi(prices, 14), 1) if prices else 50.0,
        "move_5m_pct": round(_move(prices, 5), 3),
        "move_10m_pct": round(_move(prices, 10), 3),
        "move_15m_pct": round(_move(prices, 15), 3),
        "move_30m_pct": round(_move(prices, 30), 3),
        "points": len(prices),
    }


def _status(candidate: dict[str, Any]) -> str:
    if not candidate:
        return "NOT_IN_CURRENT_SHORTLIST"
    decision = str(candidate.get("safety_decision") or "").upper()
    paper = str(candidate.get("paper_trade_status") or "").upper()
    actionable = str(candidate.get("actionable") or "").lower() == "true"
    if decision:
        return decision
    if paper:
        return paper
    if actionable:
        return "ACTIONABLE_CANDIDATE"
    return str(candidate.get("selection_tier") or candidate.get("stage") or "ANALYZED")


def analysis_payload(day: str, symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    market = _market_row(symbol)
    points = _load_points(day, symbol)
    candidate = _latest_candidate(symbol)
    technical = _technical(points, market)
    direction = str(market.get("direction") or "").upper()
    signals: list[str] = []

    if direction == "UP":
        signals.append("Price is above its 09:15 open")
    elif direction == "DOWN":
        signals.append("Price is below its 09:15 open")

    if _f(market.get("range_position_pct")) >= 80:
        signals.append("Trading near the day's upper range")
    elif _f(market.get("range_position_pct")) <= 20:
        signals.append("Trading near the day's lower range")

    if technical["rsi14_1m"] >= 70:
        signals.append("Short-term RSI is elevated")
    elif technical["rsi14_1m"] <= 30:
        signals.append("Short-term RSI is depressed")

    if technical["ema9_1m"] and technical["ema20_1m"]:
        signals.append(
            "1-minute EMA9 is above EMA20"
            if technical["ema9_1m"] > technical["ema20_1m"]
            else "1-minute EMA9 is below EMA20"
        )

    if candidate:
        for key in ("setup_family", "pivot_state", "opening_range_breakout", "opening_direction_confirmed"):
            value = candidate.get(key)
            if value not in (None, "", False, "False"):
                signals.append(f"{key.replace('_', ' ').title()}: {value}")

    return {
        "generated_at": _read_market_watch().get("generated_at", ""),
        "day": day,
        "symbol": symbol,
        "market": market,
        "technical": technical,
        "candidate": candidate,
        "candidate_status": _status(candidate),
        "points": points[-180:],
        "signals": signals[:12],
        "read_only": True,
        "trading_engine_untouched": True,
    }


STOCK_ANALYSIS_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>APlus Stock Analysis</title>
<style>
:root{--bg:#080d19;--panel:#11192b;--panel2:#0d1424;--line:#26334c;--text:#e8effc;--muted:#91a3c0;--green:#17c964;--red:#f31260;--cyan:#22d3ee}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}
.nav{position:sticky;top:0;z-index:20;display:flex;gap:7px;overflow:auto;padding:10px 14px;border-bottom:1px solid var(--line);background:#080d19}
.nav a{white-space:nowrap;color:var(--text);text-decoration:none;border:1px solid var(--line);background:var(--panel);padding:8px 11px;border-radius:9px;font-size:12px;font-weight:700}
.header{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.title{font-size:24px;font-weight:850}.sub{font-size:12px;color:var(--muted);margin-top:4px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;padding:12px 18px}.toolbar input,.toolbar button{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:9px;padding:9px 12px}.toolbar button{cursor:pointer;font-weight:700}
.wrap{padding:0 18px 22px}.cards{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:11px}.label{font-size:10px;color:var(--muted)}.value{font-size:18px;font-weight:800;margin-top:5px}.up{color:var(--green)}.down{color:var(--red)}
.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:10px;margin-top:10px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.pt{padding:11px 13px;border-bottom:1px solid var(--line);font-weight:800}.body{padding:12px}.rows{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.metric{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:9px}.metric b{display:block;font-size:13px}.metric span{font-size:11px;color:var(--muted)}
#chart{height:390px;padding:8px}.chartline{fill:none;stroke:var(--cyan);stroke-width:2.5}.gridline{stroke:var(--line);stroke-width:1}.point{font-size:10px;fill:var(--muted)}
ul{margin:0;padding-left:18px;color:#cbd7eb;font-size:12px;line-height:1.8}.notice{margin-top:10px;padding:10px 12px;border:1px solid #3a2e60;background:#15112a;border-radius:10px;color:#cfc5f7;font-size:11px}
@media(max-width:1000px){.cards{grid-template-columns:repeat(3,minmax(0,1fr))}.grid{grid-template-columns:1fr}}
@media(max-width:600px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.wrap{padding:0 10px 16px}.header{padding:12px}.toolbar{padding:10px}.title{font-size:19px}.rows{grid-template-columns:1fr}#chart{height:300px}}
</style></head>
<body>
<div class="nav">
<a href="/">LIVE TRADING</a><a href="/fno-market-watch">F&amp;O MARKET WATCH</a><a href="/stock-analysis">STOCK ANALYSIS</a>
<a href="/sector-performance">SECTOR PERFORMANCE</a><a href="/opening-structure">OPENING STRUCTURE</a><a href="/stock-charts">STOCK CHARTS</a>
</div>
<div class="header"><div><div class="title" id="title">APlus Stock Analysis</div><div class="sub">Read-only analysis layer • does not place, modify or cancel orders</div></div><div class="sub" id="updated">Loading...</div></div>
<div class="toolbar"><input id="symbol" placeholder="Enter F&amp;O symbol e.g. RELIANCE"><input type="date" id="day"><button onclick="load()">Analyze</button><button onclick="backToWatch()">← Market Watch</button></div>
<div class="wrap">
<div class="cards">
<div class="card"><div class="label">LTP</div><div class="value" id="ltp">-</div></div>
<div class="card"><div class="label">From 09:15</div><div class="value" id="fromopen">-</div></div>
<div class="card"><div class="label">Prev Close %</div><div class="value" id="prev">-</div></div>
<div class="card"><div class="label">Range Position</div><div class="value" id="range">-</div></div>
<div class="card"><div class="label">Direction</div><div class="value" id="direction">-</div></div>
<div class="card"><div class="label">APlus Status</div><div class="value" id="status">-</div></div>
</div>
<div class="grid">
<div class="panel"><div class="pt">Intraday Price / Movement</div><div id="chart"></div><div class="body"><div class="rows" id="market"></div></div></div>
<div class="panel"><div class="pt">Technical Snapshot</div><div class="body"><div class="rows" id="technical"></div></div></div>
</div>
<div class="grid">
<div class="panel"><div class="pt">APlus Scanner Context</div><div class="body"><div id="candidate"></div></div></div>
<div class="panel"><div class="pt">Why this stock is interesting</div><div class="body"><ul id="signals"></ul><div class="notice">This screen is diagnostic/read-only. It is intentionally isolated from APlus automated entry, risk, safety-gate and order-execution code.</div></div></div>
</div>
</div>
<script>
const q=s=>document.querySelector(s);
const n=v=>Number(v||0);
const pct=v=>(n(v)>=0?"+":"")+n(v).toFixed(2)+"%";
function cls(v){return n(v)>=0?"up":"down"}
function esc(v){return String(v==null?"":v).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]))}
function card(k,v){return "<div class='metric'><b>"+esc(k)+"</b><span>"+v+"</span></div>"}
function drawChart(points){
  if(!points.length){q("#chart").innerHTML="<div class='sub' style='padding:20px'>No saved intraday history for this symbol/date.</div>";return}
  const w=1000,h=350,p=34,vals=points.map(x=>n(x.ltp)).filter(x=>x>0);
  let min=Math.min(...vals),max=Math.max(...vals);if(min===max){min-=1;max+=1}
  const x=i=>p+(w-2*p)*(i/(vals.length-1||1)),y=v=>h-p-(h-2*p)*(v-min)/(max-min);
  const line=vals.map((v,i)=>x(i).toFixed(1)+","+y(v).toFixed(1)).join(" ");
  let grid="";for(let i=0;i<5;i++){const yy=p+(h-2*p)*i/4;grid+="<line class='gridline' x1='"+p+"' y1='"+yy+"' x2='"+(w-p)+"' y2='"+yy+"'/>";}
  q("#chart").innerHTML="<svg viewBox='0 0 "+w+" "+h+"' width='100%' height='100%' preserveAspectRatio='none'>"+grid+"<polyline class='chartline' points='"+line+"'/><text class='point' x='"+p+"' y='"+(h-8)+"'>"+esc(points[0].time)+"</text><text class='point' x='"+(w-p)+"' y='"+(h-8)+"' text-anchor='end'>"+esc(points[points.length-1].time)+"</text></svg>";
}
function render(d){
  const m=d.market||{},t=d.technical||{},c=d.candidate||{};
  q("#title").textContent="APlus Stock Analysis • "+d.symbol;
  q("#updated").textContent=(d.generated_at?"Market snapshot "+d.generated_at:"No market snapshot")+" • "+(d.read_only?"READ ONLY":"");
  q("#ltp").textContent=m.ltp?Number(m.ltp).toLocaleString("en-IN",{maximumFractionDigits:2}):"-";
  q("#fromopen").textContent=pct(m.from_open_pct);q("#fromopen").className="value "+cls(m.from_open_pct);
  q("#prev").textContent=pct(m.from_prev_close_pct);q("#prev").className="value "+cls(m.from_prev_close_pct);
  q("#range").textContent=n(m.range_position_pct).toFixed(1)+"%";
  q("#direction").textContent=m.direction||"-";q("#direction").className="value "+(m.direction==="UP"?"up":m.direction==="DOWN"?"down":"");
  q("#status").textContent=d.candidate_status||"-";
  q("#status").className="value "+(String(d.candidate_status).includes("BLOCK")?"down":String(d.candidate_status).includes("ACTION")?"up":"");
  q("#market").innerHTML=[
    card("Sector",esc(m.sector||"UNCLASSIFIED")),card("09:15 Open",n(m.open_0915).toFixed(2)),
    card("Previous Close",n(m.previous_close).toFixed(2)),card("Gap",pct(m.gap_pct)),
    card("Day High",n(m.day_high).toFixed(2)),card("Day Low",n(m.day_low).toFixed(2)),
    card("From Open",pct(m.from_open_pct)),card("From Prev Close",pct(m.from_prev_close_pct))
  ].join("");
  q("#technical").innerHTML=[
    card("EMA9 (1m)",n(t.ema9_1m).toFixed(2)),card("EMA20 (1m)",n(t.ema20_1m).toFixed(2)),
    card("EMA50 (1m)",n(t.ema50_1m).toFixed(2)),card("RSI14 (1m)",n(t.rsi14_1m).toFixed(1)),
    card("5m Move",pct(t.move_5m_pct)),card("10m Move",pct(t.move_10m_pct)),
    card("15m Move",pct(t.move_15m_pct)),card("30m Move",pct(t.move_30m_pct))
  ].join("");
  if(c && Object.keys(c).length){
    const keys=["stage","selection_tier","setup_family","score","trade_quality_score","movement_capture_score","trend_alignment_score","clean_trend_score","chase_risk_score","relative_volume","recent_relative_volume_15m","vwap","vwap_distance_percent","ema9_5m","ema20_5m","ema50_5m","ema9_15m","ema20_15m","rsi14_5m","adx14_5m","plus_di_5m","minus_di_5m","pivot_state","pivot_point","r1","r2","s1","s2","opening_range_breakout","opening_direction_confirmed","safety_decision","paper_trade_status"];
    q("#candidate").innerHTML=keys.filter(k=>c[k]!==undefined&&c[k]!==""&&c[k]!==null).map(k=>card(k.replaceAll("_"," "),esc(c[k]))).join("");
  }else{
    q("#candidate").innerHTML="<div class='sub'>This stock is not in the current detailed APlus candidate shortlist. Market-watch and locally calculated technical data are still shown.</div>";
  }
  q("#signals").innerHTML=(d.signals||[]).map(x=>"<li>"+esc(x)+"</li>").join("")||"<li>No additional local signals available.</li>";
  drawChart(d.points||[]);
}
async function load(){
  const sym=q("#symbol").value.trim().toUpperCase();if(!sym)return;
  const day=q("#day").value;
  const r=await fetch("/api/stock-analysis?symbol="+encodeURIComponent(sym)+"&day="+encodeURIComponent(day)+"&ts="+Date.now());
  render(await r.json());
}
function backToWatch(){location.href="/fno-market-watch"}
const params=new URLSearchParams(location.search);
q("#symbol").value=(params.get("symbol")||"").toUpperCase();
const now=new Date();const localDate=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,10);
q("#day").value=params.get("day")||localDate;
if(q("#symbol").value){load();setInterval(load,5000);}
</script></body></html>"""


__all__ = ["STOCK_ANALYSIS_HTML", "analysis_payload"]
