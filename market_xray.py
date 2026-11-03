"""Market X-Ray: every F&O stock's move from the open as one live picture (READ-ONLY, display only).

    /xray              the page
    /api/market-xray   JSON for the page

Data (no network): data/reports/fno_market_watch_latest.json for each stock's 09:15 open, last price, previous close and sector, and
the order-book recorder's per-minute prices (data/order_book/<day>.csv, read through stock_trend.ticks_today) for the day's path.
Lines are coloured by DIRECTION: green when the stock is above its open now, red when below.
"""

from __future__ import annotations

import json
import statistics as st
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OPEN_MIN = 9 * 60 + 15
GRID = 5                                   # minutes between plotted points


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def grid_path(points: list[tuple[int, float]], open_px: float, upto: int) -> list[float | None]:
    """% from the open at every GRID minutes from 09:15 to `upto`, carrying the last known price forward; None before the first tick."""
    out: list[float | None] = []
    j, last = 0, None
    for m in range(OPEN_MIN, upto + 1, GRID):
        while j < len(points) and points[j][0] <= m:
            last = points[j][1]
            j += 1
        out.append(round((last / open_px - 1.0) * 100.0, 3) if (last and open_px > 0) else None)
    return out


def build(rows: list[dict[str, Any]], ticks: dict[str, list[tuple[int, float]]], now_minute: int) -> dict[str, Any]:
    upto = max(OPEN_MIN, min(now_minute, 15 * 60 + 30))
    upto -= (upto - OPEN_MIN) % GRID
    minutes = list(range(OPEN_MIN, upto + 1, GRID))
    stocks: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get("symbol") or "")
        op, ltp = _f(r.get("open_0915")), _f(r.get("ltp"))
        if not sym or op <= 0 or ltp <= 0:
            continue
        path = grid_path(ticks.get(sym) or [], op, upto)
        if path:
            path[-1] = round((ltp / op - 1.0) * 100.0, 3)          # the last point is always the live price
        stocks.append({"s": sym, "sector": str(r.get("sector") or "Other"), "last": round((ltp / op - 1.0) * 100.0, 2),
                       "prev": round(_f(r.get("from_prev_close_pct")), 2), "p": path})
    bull = sum(1 for s in stocks if s["last"] > 0)
    bear = sum(1 for s in stocks if s["last"] < 0)
    sectors: dict[str, list[float]] = {}
    for s in stocks:
        sectors.setdefault(s["sector"], []).append(s["last"])
    sec_rows = [{"name": k, "avg": round(st.mean(v), 2), "n": len(v), "up": sum(1 for x in v if x > 0),
                 "bars": sorted(v, reverse=True)} for k, v in sectors.items()]
    sec_rows.sort(key=lambda x: -x["avg"])
    ranked = [x for x in sec_rows if x["n"] >= 3] or sec_rows            # a one- or two-stock "sector" is not a sector leader
    return {"ok": True, "minutes": minutes, "stocks": stocks, "bullish": bull, "bearish": bear, "flat": len(stocks) - bull - bear,
            "sectors": sec_rows, "leading": ranked[0] if ranked else None, "lagging": ranked[-1] if ranked else None,
            "now": f"{upto // 60:02d}:{upto % 60:02d}"}


def payload(root: Path = ROOT) -> dict[str, Any]:
    try:
        mw = json.loads((root / "data" / "reports" / "fno_market_watch_latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "market watch report not available"}
    rows = mw.get("rows") or []
    try:
        import stock_trend

        ticks = stock_trend.ticks_today(root)
    except Exception:                                      # noqa: BLE001 - the lines are an extra; counts and sectors still work
        ticks = {}
    now = datetime.now()
    out = build(rows, ticks, now.hour * 60 + now.minute)
    out["updated"] = now.strftime("%H:%M:%S")
    out["report_at"] = str(mw.get("generated_at") or "")[11:19]
    return out


XRAY_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Market X-Ray</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#070b14;--panel:#0d1424;--line:#1f2a44;--text:#e7eefc;--muted:#8ea0bd;--green:#19d38a;--red:#ff4d6a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.35 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1700px;margin:0 auto;padding:10px 14px 30px}a{color:#4c8dff;text-decoration:none;font-weight:700}
.top{display:flex;flex-wrap:wrap;gap:14px;align-items:center;justify-content:space-between;margin:8px 0}
.big{font-size:34px;font-weight:900;line-height:1}.green{color:var(--green)}.red{color:var(--red)}.muted{color:var(--muted)}
.cnt{display:flex;gap:22px}.cnt small{display:block;color:var(--muted);font-size:11px;letter-spacing:.08em}
.sect{font-size:13px}.sect b{font-size:15px}
.grid{display:grid;grid-template-columns:230px 1fr 230px;gap:10px}@media(max-width:1100px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:8px}
.sl{max-height:640px;overflow:auto}.sr{display:grid;grid-template-columns:1fr auto;gap:2px 8px;padding:5px 6px;border-radius:8px;cursor:pointer;margin-bottom:3px}
.sr:hover,.sr.on{background:#16213a}.sr .nm{font-weight:700;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sr .bars{grid-column:1/3;display:flex;height:6px;gap:1px}.sr .bars i{flex:1;border-radius:1px}
canvas{display:block;width:100%}
#tip{position:fixed;pointer-events:none;background:#0b1224ee;border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12.5px;display:none;z-index:9}
.hint{color:var(--muted);font-size:12px;margin-top:6px}
</style></head><body><div class="wrap">
<div><a href="/">&larr; Dashboard</a> &nbsp; <a href="/pipeline">Pipeline</a> &nbsp; <a href="/fno-market-watch">Market Watch</a></div>
<div class="top">
 <div class="cnt"><div><small>BULLISH</small><span class="big green" id="bull">-</span></div><div><small>BEARISH</small><span class="big red" id="bear">-</span></div></div>
 <div class="sect" id="lead"></div><div class="sect" id="lag"></div><div class="muted" id="upd"></div>
</div>
<div class="panel"><canvas id="dots" height="86"></canvas></div>
<div class="grid" style="margin-top:10px">
 <div class="panel sl" id="secs"></div>
 <div class="panel"><canvas id="race" height="560"></canvas><div class="hint">Each line is one stock's move from its 09:15 open. Green = above its open now, red = below. Hover to identify, click to open it. Click a sector on the left to focus it.</div></div>
 <div class="panel"><canvas id="rank" height="560"></canvas></div>
</div></div><div id="tip"></div>
<script>
var D=null,focus=null,hover=null,GREEN="25,211,138",RED="255,77,106";
function fit(c,h){var w=c.clientWidth,dpr=window.devicePixelRatio||1;c.width=w*dpr;c.height=h*dpr;c.style.height=h+"px";var g=c.getContext("2d");g.setTransform(dpr,0,0,dpr,0,0);return {g:g,w:w,h:h}}
function inFocus(s){return !focus||s.sector===focus}
function drawDots(){var c=fit(document.getElementById("dots"),86),g=c.g,w=c.w,h=c.h,pad=40,mx=5;g.clearRect(0,0,w,h);
 g.strokeStyle="#1f2a44";g.beginPath();g.moveTo(pad,h/2);g.lineTo(w-pad,h/2);g.stroke();
 g.fillStyle="#8ea0bd";g.font="11px system-ui";[-4,-2,0,2,4].forEach(function(v){var x=pad+(v+mx)/(2*mx)*(w-2*pad);g.fillText((v>0?"+":"")+v+"%",x-10,h-4)});
 var seed=7;D.stocks.forEach(function(s,i){seed=(seed*9301+49297)%233280;var j=(seed/233280-0.5)*34;var v=Math.max(-mx,Math.min(mx,s.last));
  var x=pad+(v+mx)/(2*mx)*(w-2*pad),y=h/2-8+j*0.8;g.fillStyle="rgba("+(s.last>=0?GREEN:RED)+","+(inFocus(s)?0.9:0.15)+")";g.beginPath();g.arc(x,y,2.6,0,6.3);g.fill()})}
function drawRace(){var c=fit(document.getElementById("race"),560),g=c.g,w=c.w,h=c.h,L=44,R=70,T=10,B=22;g.clearRect(0,0,w,h);
 var ms=D.minutes,n=ms.length;if(n<2)return;var all=[];D.stocks.forEach(function(s){s.p.forEach(function(v){if(v!=null)all.push(v)})});
 var mx=Math.max(1,Math.min(8,Math.max.apply(null,all.map(Math.abs))||1));
 var X=function(i){return L+i/(n-1)*(w-L-R)},Y=function(v){return T+(mx-v)/(2*mx)*(h-T-B)};
 g.strokeStyle="#1f2a44";g.fillStyle="#8ea0bd";g.font="11px system-ui";
 for(var v=-Math.floor(mx);v<=Math.floor(mx);v++){g.beginPath();g.moveTo(L,Y(v));g.lineTo(w-R,Y(v));g.lineWidth=v===0?1.6:0.5;g.stroke();g.fillText((v>0?"+":"")+v+"%",4,Y(v)+4)}
 g.lineWidth=1;for(var i=0;i<n;i+=Math.ceil(n/8)){var m=ms[i];g.fillText(("0"+Math.floor(m/60)).slice(-2)+":"+("0"+m%60).slice(-2),X(i)-14,h-6)}
 var order=D.stocks.slice().sort(function(a,b){return (inFocus(a)?1:0)-(inFocus(b)?1:0)});
 order.forEach(function(s){var f=inFocus(s),hv=hover&&hover.s===s.s;
  g.strokeStyle="rgba("+(s.last>=0?GREEN:RED)+","+(hv?1:(f?0.38:0.06))+")";g.lineWidth=hv?2.4:(f?1:0.8);g.beginPath();var st=false;
  s.p.forEach(function(v,i){if(v==null)return;var x=X(i),y=Y(Math.max(-mx,Math.min(mx,v)));if(!st){g.moveTo(x,y);st=true}else g.lineTo(x,y)});g.stroke()});
 D._race={X:X,Y:Y,mx:mx,L:L,R:R,T:T,B:B,w:w,h:h}}
function drawRank(){var c=fit(document.getElementById("rank"),560),g=c.g,w=c.w,h=c.h;g.clearRect(0,0,w,h);
 var arr=D.stocks.slice().sort(function(a,b){return b.last-a.last}),n=arr.length,bh=Math.max(1,(h-8)/n),mid=w*0.5,mx=Math.max(1,Math.max.apply(null,arr.map(function(s){return Math.abs(s.last)})));
 g.font="10px system-ui";
 arr.forEach(function(s,i){var y=4+i*bh,len=Math.abs(s.last)/mx*(w*0.46),f=inFocus(s),hv=hover&&hover.s===s.s;
  g.fillStyle="rgba("+(s.last>=0?GREEN:RED)+","+(hv?1:(f?0.75:0.15))+")";g.fillRect(s.last>=0?mid:mid-len,y,len,Math.max(1,bh-1));
  if(i<10||i>=n-10||hv){g.fillStyle=f?"#e7eefc":"#556";g.textAlign=s.last>=0?"right":"left";g.fillText(s.s+" "+(s.last>0?"+":"")+s.last.toFixed(1),s.last>=0?mid-4:mid+4,y+Math.min(bh,9))}});g.textAlign="left";
 D._rank={arr:arr,bh:bh,h:h}}
function drawSecs(){var el=document.getElementById("secs");
 el.innerHTML=D.sectors.map(function(s){var cl=s.avg>=0?"green":"red";
  return'<div class="sr'+(focus===s.name?" on":"")+'" data-n="'+s.name.replace(/"/g,"&quot;")+'"><span class="nm">'+s.name+'</span><b class="'+cl+'">'+(s.avg>0?"+":"")+s.avg.toFixed(2)+'%</b><div class="bars">'
   +s.bars.map(function(v){return'<i style="background:'+(v>=0?"#19d38a":"#ff4d6a")+';opacity:'+Math.min(1,0.35+Math.abs(v)/3)+'"></i>'}).join("")+'</div></div>'}).join("");
 el.querySelectorAll(".sr").forEach(function(r){r.onclick=function(){focus=(focus===r.dataset.n)?null:r.dataset.n;draw()}})}
function draw(){if(!D||!D.ok)return;
 document.getElementById("bull").textContent=D.bullish;document.getElementById("bear").textContent=D.bearish;
 var L=D.leading,G=D.lagging;
 document.getElementById("lead").innerHTML=L?'<span class="muted">LEADING SECTOR</span> <b class="green">'+L.name+' +'+L.avg.toFixed(2)+'%</b>':"";
 document.getElementById("lag").innerHTML=G?'<span class="muted">LAGGING SECTOR</span> <b class="red">'+G.name+' '+G.avg.toFixed(2)+'%</b>':"";
 document.getElementById("upd").textContent="Updated "+D.updated+" - lines to "+D.now+" - "+D.stocks.length+" stocks";
 drawDots();drawRace();drawRank();drawSecs()}
function nearest(ev){var r=document.getElementById("race").getBoundingClientRect(),x=ev.clientX-r.left,y=ev.clientY-r.top,rc=D&&D._race;if(!rc)return null;
 var n=D.minutes.length,i=Math.round((x-rc.L)/(rc.w-rc.L-rc.R)*(n-1));if(i<0||i>=n)return null;var best=null,bd=9;
 D.stocks.forEach(function(s){if(!inFocus(s))return;var v=s.p[i];if(v==null)return;var d=Math.abs(rc.Y(Math.max(-rc.mx,Math.min(rc.mx,v)))-y);if(d<bd){bd=d;best=s}});return best}
var tip=document.getElementById("tip");
document.getElementById("race").addEventListener("mousemove",function(ev){var s=nearest(ev);hover=s;
 if(s){tip.style.display="block";tip.style.left=(ev.clientX+14)+"px";tip.style.top=(ev.clientY+10)+"px";
  tip.innerHTML='<b>'+s.s+'</b> <span class="muted">'+s.sector+'</span><br><span class="'+(s.last>=0?"green":"red")+'">'+(s.last>0?"+":"")+s.last.toFixed(2)+'% from open</span> &middot; '+(s.prev>0?"+":"")+s.prev.toFixed(2)+'% vs prev close'}else tip.style.display="none";
 drawRace();drawRank()});
document.getElementById("race").addEventListener("mouseleave",function(){hover=null;tip.style.display="none";drawRace();drawRank()});
document.getElementById("race").addEventListener("click",function(ev){var s=nearest(ev);if(s)location.href="/stock-analysis?symbol="+encodeURIComponent(s.s)});
document.getElementById("rank").addEventListener("click",function(ev){var rc=D&&D._rank;if(!rc)return;var r=ev.target.getBoundingClientRect(),i=Math.floor((ev.clientY-r.top-4)/rc.bh);if(i>=0&&i<rc.arr.length)location.href="/stock-analysis?symbol="+encodeURIComponent(rc.arr[i].s)});
function load(){fetch("/api/market-xray",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;draw()}).catch(function(){})}
window.addEventListener("resize",function(){draw()});load();setInterval(load,15000);
</script></body></html>
"""
