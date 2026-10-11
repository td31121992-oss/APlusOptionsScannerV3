"""Sector Analysis page: a one-line story of the day, index and breadth cards, a sector ranking (move / breadth / turnover) and a heatmap
of every F&O stock grouped by sector (block size = turnover, colour = % change from the previous close). Read-only.

Built from data APlus already holds: the scanner's market-watch rows (price, previous close, sector), the order-book recorder (day volume
-> turnover, and a per-minute equal-weight F&O index) and the Nifty readings in data/market_context.
"""

from __future__ import annotations

import csv
import json
import threading
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import money_flow

ROOT = Path(__file__).resolve().parent
_LOCK = threading.Lock()
_S: dict[str, Any] = {"key": None, "offset": 0, "header": None, "minutes": {}}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _market_rows(root: Path) -> list[dict[str, Any]]:
    try:
        return (json.loads((root / "data" / "reports" / "fno_market_watch_latest.json").read_text(encoding="utf-8"))).get("rows", [])
    except (OSError, ValueError):
        return []


def _index_series(root: Path, day: date, prev: dict[str, float]) -> list[tuple[str, float]]:
    """Equal-weight F&O index: the average % change from the previous close across all stocks, one point per minute."""
    path = root / "data" / "order_book" / f"{day.isoformat()}.csv"
    key = f"{root}|{day}"
    if _S["key"] != key:
        _S.update(key=key, offset=0, header=None, minutes={})
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size < _S["offset"]:
        _S.update(offset=0, header=None, minutes={})
    if size > _S["offset"]:
        with path.open("rb") as handle:
            handle.seek(_S["offset"])
            chunk = handle.read()
        end = chunk.rfind(b"\n")
        if end >= 0:
            _S["offset"] += end + 1
            lines = chunk[: end + 1].decode("utf-8", errors="replace").splitlines()
            if _S["header"] is None and lines:
                _S["header"] = next(csv.reader([lines.pop(0)]))
            head = _S["header"] or []
            for row in csv.reader(lines):
                if len(row) != len(head):
                    continue
                r = dict(zip(head, row))
                p, ltp = prev.get(r.get("symbol", ""), 0.0), _f(r.get("ltp"))
                t = r.get("time", "")[11:16]
                if p > 0 and ltp > 0 and t:
                    acc = _S["minutes"].setdefault(t, [0.0, 0])
                    acc[0] += (ltp / p - 1) * 100
                    acc[1] += 1
    return [(t, round(s / n, 3)) for t, (s, n) in sorted(_S["minutes"].items()) if n >= 50]


def _nifty(root: Path, day: date) -> dict[str, Any]:
    try:
        with (root / "data" / "market_context" / f"{day.isoformat()}.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return {}
    if not rows:
        return {}
    pts = [(r["time"][11:16], _f(r.get("nifty_ltp"))) for r in rows if _f(r.get("nifty_ltp")) > 0]
    last = rows[-1]
    return {"ltp": _f(last.get("nifty_ltp")), "chg_pct": _f(last.get("nifty_pct_prev")), "open_pct": _f(last.get("nifty_pct_open")),
            "series": pts[:: max(1, len(pts) // 90)]}


def sector_table(rows: list[dict[str, Any]], turnover: dict[str, float]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r.get("sector") or "Other", []).append(r)
    out = []
    for name, items in groups.items():
        chg = [_f(i.get("from_prev_close_pct")) for i in items]
        up = sum(1 for c in chg if c > 0)
        out.append({"sector": name, "stocks": len(items), "move": round(sum(chg) / len(chg), 2), "median": round(median(chg), 2),
                    "breadth": round(up / len(items) * 100), "up": up, "down": sum(1 for c in chg if c < 0),
                    "turnover_cr": round(sum(turnover.get(i["symbol"], 0.0) for i in items), 1)})
    return sorted(out, key=lambda s: -s["move"])


def headline(gap: float, day_move: float, early: float | None, up_pct: float) -> tuple[str, str]:
    """A plain one-line story of the session so far (rule-based, never a forecast)."""
    if abs(gap) < 0.3:
        opening = "A quiet open"
    elif gap >= 0.8:
        opening = "A strong gap-up open"
    elif gap > 0:
        opening = "A gap-up open"
    elif gap <= -0.8:
        opening = "A sharp gap-down open"
    else:
        opening = "A gap-down open"
    late = early is not None and abs(day_move) > 0 and abs(early) < abs(day_move) * 0.4
    if day_move >= 0.4:
        shape = "then a late climb" if late else "then a steady climb"
    elif day_move <= -0.4:
        shape = "then a late slide" if late else "then a steady slide"
    else:
        shape = "then a sideways session"
    tone = "broad strength" if up_pct >= 75 else "broad weakness" if up_pct <= 25 else "a mixed market"
    return f"{opening}, {shape}.", tone


def payload(root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    day = today or date.today()
    rows = _market_rows(root)
    if not rows:
        return {"ok": False, "error": "market-watch data not available yet"}
    prev = {r["symbol"]: _f(r.get("previous_close")) for r in rows}
    flow = money_flow.payload(0, root, day)
    turnover = {s["symbol"]: s["traded_cr"] for s in flow.get("stocks", [])} if flow.get("ok") else {}
    recent_flow = money_flow.payload(15, root, day)
    recent = {s["symbol"]: s["traded_cr"] for s in recent_flow.get("stocks", [])} if recent_flow.get("ok") else {}
    with _LOCK:
        try:
            series = _index_series(root, day, prev)
        except Exception:                                  # noqa: BLE001
            series = []
    chg = [_f(r.get("from_prev_close_pct")) for r in rows]
    up, down = sum(1 for c in chg if c > 0), sum(1 for c in chg if c < 0)
    secs = sector_table(rows, turnover)
    gap = median([_f(r.get("gap_pct")) for r in rows])
    early = None
    if series:
        base = series[0][1]
        at = next((v for t, v in series if t >= "10:15"), series[-1][1])
        early = at - base
    day_move = sum(chg) / len(chg)
    story, tone = headline(gap, day_move, early, up / len(rows) * 100)
    stocks = [{"symbol": r["symbol"], "sector": r.get("sector") or "Other", "chg": round(_f(r.get("from_prev_close_pct")), 2),
               "gap": round(_f(r.get("gap_pct")), 2), "turnover_cr": turnover.get(r["symbol"], 0.0), "recent_cr": recent.get(r["symbol"], 0.0),
               "ltp": _f(r.get("ltp"))} for r in rows]
    by_recent = sorted(stocks, key=lambda x: -(x["recent_cr"] or x["turnover_cr"]))
    active = [x["symbol"] for x in by_recent[:25]]
    leading = sum(1 for x in stocks if x["chg"] > day_move)
    lagging = sum(1 for x in stocks if x["chg"] < day_move)
    most = max(secs, key=lambda s: s["turnover_cr"]) if secs and any(s["turnover_cr"] for s in secs) else None
    return {"ok": True, "story": story, "tone": tone, "as_of": series[-1][0] if series else "", "total": len(rows), "up": up, "down": down, "flat": len(rows) - up - down,
            "fno_index": {"chg_pct": round(day_move, 2), "series": series[:: max(1, len(series) // 90)]}, "nifty": _nifty(root, day),
            "active": active, "most_active": active[:3], "leading": leading, "lagging": lagging,
            "strongest": secs[0] if secs else None, "weakest": secs[-1] if secs else None, "most_traded": most, "sectors": secs, "stocks": stocks}


SECTOR_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Sector Analysis</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#2ecc71;--red:#ff6363;--blue:#4c8dff;--amber:#f5b942}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1250px;margin:0 auto;padding:14px}a.nav{color:var(--blue);text-decoration:none;font-weight:700;margin-right:12px}
h1{font-size:30px;margin:14px 0 4px;letter-spacing:-.01em}.sub{color:var(--muted);font-size:13px}.k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin:14px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
.card .v{font-size:26px;font-weight:800;margin:4px 0}.up{color:var(--green);font-weight:700}.dn{color:var(--red);font-weight:700}
.hl{border-color:#e8793a}.hl .r{display:flex;justify-content:space-between;margin:5px 0}
.bar2{height:8px;border-radius:5px;background:var(--red);overflow:hidden;margin:8px 0}.bar2 div{height:100%;background:var(--green)}
.grid{display:grid;grid-template-columns:minmax(280px,340px) 1fr minmax(260px,320px);gap:12px}@media(max-width:1250px){.grid{grid-template-columns:minmax(280px,340px) 1fr}.grid .act{grid-column:1 / -1}}@media(max-width:900px){.grid{grid-template-columns:1fr}}.fbar{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}.fbar button{background:transparent;color:var(--muted);border:1px solid var(--line);border-radius:7px;padding:4px 10px;font:inherit;cursor:pointer}.fbar button.on{background:var(--blue);color:#fff;border-color:var(--blue)}.gap{display:inline-block;font-size:9px;font-weight:800;padding:1px 4px;border-radius:3px;background:#3b2a7a;color:#d9ccff;margin-top:2px}.mini{background:#0f1729;border:1px solid var(--line);border-radius:8px;margin-bottom:8px;padding:6px}.mini .t{display:flex;justify-content:space-between;font-weight:700;margin-bottom:2px}.mini .ch{height:150px}
.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
.tabs button{background:transparent;color:var(--muted);border:1px solid var(--line);border-radius:7px;padding:5px 11px;font:inherit;cursor:pointer;margin-right:4px}.tabs button.on{background:var(--blue);color:#fff;border-color:var(--blue)}
.srow{display:grid;grid-template-columns:120px 1fr 64px;gap:8px;align-items:center;padding:5px 4px;border-radius:6px;cursor:pointer}.srow:hover,.srow.sel{background:#16213b}
.track{position:relative;height:12px;background:#0f1729;border-radius:4px}.mid{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#3a4968}.fill{position:absolute;top:1px;bottom:1px;border-radius:3px}
#map{position:relative;width:100%;height:520px;background:#0b1020;border-radius:8px;overflow:hidden}.cell{position:absolute;overflow:hidden;border:1px solid #0b1020;font-size:11px;line-height:1.15;padding:3px 4px;color:#fff;cursor:pointer}
.sechead{position:absolute;font-size:10.5px;color:#cfd8ea;text-transform:uppercase;letter-spacing:.05em;padding:2px 4px;pointer-events:none;overflow:hidden;white-space:nowrap}
.legend{display:flex;gap:10px;align-items:center;margin-top:8px;color:var(--muted);font-size:12px}.sw{width:60px;height:10px;border-radius:5px;background:linear-gradient(90deg,#b23a3a,#2a3350,#1f9d55)}
svg.sp{width:100%;height:36px}
</style></head><body><div class="wrap">
<div><a class="nav" href="/">Dashboard</a><a class="nav" href="/money-flow">Money flow</a><a class="nav" href="/fno-market-watch">Market watch</a><a class="nav" href="/live-scanner">Live scanner</a></div>
<div class="k" id="kicker">sectoral analysis</div><h1 id="story">loading...</h1><div class="sub" id="line"></div>
<div class="cards" id="cards"></div>
<div class="grid"><div class="box"><div class="k">Sector performance</div><div class="sub" style="margin:2px 0 8px">Average move of each sector's stocks today. Click a sector to open it.</div>
<div class="tabs" id="tabs"><button data-m="move" class="on">Move</button><button data-m="breadth">Breadth</button><button data-m="turnover">Turnover</button></div><div id="secs" style="margin-top:8px"></div></div>
<div class="box"><div class="k">The F&amp;O market, like a heatmap</div><div class="sub" style="margin:2px 0 8px">Every F&amp;O stock is a block, grouped by sector. Bigger = more money traded today. Colour = % change from the previous close. Click a block to open the stock.</div>
<div class="fbar" id="fbar"><button data-f="ALL" class="on">All</button><button data-f="TOP">Most active 25</button><button data-f="BULL">Bull</button><button data-f="BEAR">Bear</button><button data-f="GAPS">Gaps</button></div><div class="sub" id="showing" style="margin-bottom:6px"></div><div id="map"></div><div class="legend"><span>falling</span><span class="sw"></span><span>rising</span><span style="margin-left:auto" id="mapnote"></span></div></div>
<div class="box act"><div class="k">Most active now</div><div class="sub" style="margin:2px 0 8px">5-minute candles of the stocks with the most money traded in the last 15 minutes.</div><div id="minis"></div></div></div>
<div class="sub" style="margin-top:12px">Index = equal-weight average of all F&amp;O stocks. Turnover is estimated from the order-book recorder (volume x price). It describes today so far; it is not a forecast or a trade signal.</div>
</div><script src="/static/lightweight-charts.js"></script><script>
var D=null,mode="move",sel=null,ff="ALL",charts={};
function f(n,d){return (n>0?"+":"")+Number(n).toFixed(d==null?2:d)}function c(n){return n>0?"up":n<0?"dn":""}
function spark(pts){if(!pts||pts.length<2)return"";var v=pts.map(function(p){return p[1]!=null?p[1]:p}),mn=Math.min.apply(null,v),mx=Math.max.apply(null,v),rg=(mx-mn)||1;
 var d=v.map(function(y,i){return (i/(v.length-1)*300).toFixed(1)+","+(34-(y-mn)/rg*32).toFixed(1)}).join(" ");return '<svg class="sp" viewBox="0 0 300 36" preserveAspectRatio="none"><polyline fill="none" stroke="#4c8dff" stroke-width="1.6" points="'+d+'"/></svg>'}
function load(){fetch("/api/sector-analysis",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){var first=!D;D=d;render();if(first)minis()}).catch(function(){document.getElementById("line").textContent="connection lost - retrying"})}
function render(){if(!D)return;if(!D.ok){document.getElementById("story").textContent=D.error||"no data";return}
 document.getElementById("story").textContent=D.story;var s=D.strongest,w=D.weakest;
 document.getElementById("line").textContent=D.up+" of "+D.total+" stocks green - strongest "+s.sector+" "+f(s.move)+"% - weakest "+w.sector+" "+f(w.move)+"%"+(D.as_of?" - readings to "+D.as_of:"");
 var n=D.nifty||{},up=D.up/D.total*100,mt=D.most_traded;
 document.getElementById("cards").innerHTML=
  '<div class="card"><div class="k">Nifty 50</div><div class="v">'+(n.ltp?n.ltp.toLocaleString("en-IN",{maximumFractionDigits:2}):"-")+' <span class="'+c(n.chg_pct)+'" style="font-size:14px">'+(n.ltp?f(n.chg_pct)+"%":"")+'</span></div>'+spark(n.series)+'<div class="sub">'+(n.ltp?f(n.open_pct)+"% since the open":"")+'</div></div>'
  +'<div class="card"><div class="k">APlus F&amp;O index</div><div class="v"><span class="'+c(D.fno_index.chg_pct)+'">'+f(D.fno_index.chg_pct)+'%</span></div>'+spark(D.fno_index.series)+'<div class="sub">all '+D.total+' stocks, equal weight</div></div>'
  +'<div class="card"><div class="k">Breadth</div><div class="v"><span class="up">'+D.up+'</span> <span style="color:#8ea0bd;font-size:14px">up</span> &nbsp;<span class="dn">'+D.down+'</span> <span style="color:#8ea0bd;font-size:14px">down</span></div><div class="bar2"><div style="width:'+up+'%"></div></div><div class="sub">of '+D.total+' F&amp;O stocks</div></div>'
  +'<div class="card"><div class="k">Against the F&amp;O index</div><div class="v"><span class="up">'+D.leading+'</span> <span style="color:#8ea0bd;font-size:14px">leading</span> &nbsp;<span class="dn">'+D.lagging+'</span> <span style="color:#8ea0bd;font-size:14px">lagging</span></div><div class="sub">stocks doing better / worse than the index ('+f(D.fno_index.chg_pct)+'%)</div></div>'
  +'<div class="card hl"><div class="k">Sectors</div><div class="r"><span>Strongest</span><span><b>'+s.sector+'</b> <span class="up">'+f(s.move)+'%</span></span></div><div class="r"><span>Weakest</span><span><b>'+w.sector+'</b> <span class="'+c(w.move)+'">'+f(w.move)+'%</span></span></div><div class="r"><span>Most traded</span><span><b>'+(mt?mt.sector:"-")+'</b> <span class="sub">'+(mt?Math.round(mt.turnover_cr).toLocaleString("en-IN")+" cr":"")+'</span></span></div></div>';
 var key=mode==="move"?"move":mode==="breadth"?"breadth":"turnover_cr",arr=D.sectors.slice().sort(function(a,b){return b[key]-a[key]}),mx=Math.max.apply(null,arr.map(function(x){return Math.abs(x[key])}))||1;
 document.getElementById("secs").innerHTML=arr.map(function(x){var v=x[key],bar,txt;
  if(mode==="move"){var wd=Math.min(50,Math.abs(v)/mx*50);bar='<div class="mid"></div><div class="fill" style="background:'+(v>=0?"#2ecc71":"#ff6363")+';'+(v>=0?"left:50%":"right:50%")+';width:'+wd+'%"></div>';txt='<span class="'+c(v)+'">'+f(v)+'%</span>'}
  else if(mode==="breadth"){bar='<div class="mid"></div><div class="fill" style="background:'+(v>=50?"#2ecc71":"#ff6363")+';left:0;width:'+v+'%"></div>';txt=v+'% up'}
  else{bar='<div class="fill" style="background:#4c8dff;left:0;width:'+(v/mx*100)+'%"></div>';txt=Math.round(v).toLocaleString("en-IN")+' cr'}
  return '<div class="srow'+(sel===x.sector?" sel":"")+'" data-s="'+x.sector+'"><div><b style="font-size:12.5px">'+x.sector+'</b><div class="sub" style="font-size:11px">'+x.stocks+' stocks</div></div><div class="track">'+bar+'</div><div style="text-align:right;font-size:12.5px">'+txt+'</div></div>'}).join("");
 drawMap()}
function colour(ch){var t=Math.max(-3,Math.min(3,ch))/3;if(t>=0){var a=Math.round(42+(31-42)*t),b=Math.round(51+(157-51)*t),d=Math.round(80+(85-80)*t);return"rgb("+a+","+b+","+d+")"}t=-t;return"rgb("+Math.round(42+(178-42)*t)+","+Math.round(51+(58-51)*t)+","+Math.round(80+(58-80)*t)+")"}
function worst(row,area,side){var mx=Math.max.apply(null,row.map(function(i){return i.a})),mn=Math.min.apply(null,row.map(function(i){return i.a}));return Math.max(side*side*mx/(area*area),area*area/(side*side*mn))}
function layout(items,rect){var out=[],rem=items.slice(),r={x:rect.x,y:rect.y,w:rect.w,h:rect.h},total=rem.reduce(function(a,i){return a+i.v},0)||1,sc=r.w*r.h/total;rem.forEach(function(i){i.a=i.v*sc});
 while(rem.length&&r.w>1&&r.h>1){var side=Math.min(r.w,r.h),row=[rem[0]],ra=rem[0].a,wr=worst(row,ra,side),k=1;
  while(k<rem.length){var na=ra+rem[k].a,nr=row.concat([rem[k]]),nw=worst(nr,na,side);if(nw<=wr){row=nr;ra=na;wr=nw;k++}else break}
  var th=ra/side,pos=0;if(r.w>=r.h){row.forEach(function(i){var hh=i.a/th;out.push({i:i,x:r.x,y:r.y+pos,w:th,h:hh});pos+=hh});r.x+=th;r.w-=th}else{row.forEach(function(i){var ww=i.a/th;out.push({i:i,x:r.x+pos,y:r.y,w:ww,h:th});pos+=ww});r.y+=th;r.h-=th}
  rem=rem.slice(row.length)}return out}
function drawMap(){var el=document.getElementById("map"),W=el.clientWidth,H=el.clientHeight,html="",hasT=D.stocks.some(function(s){return s.turnover_cr>0});
 var act={};(D.active||[]).forEach(function(x){act[x]=1});
 var secs={};D.stocks.forEach(function(s){if(sel&&s.sector!==sel)return;if(ff==="TOP"&&!act[s.symbol])return;if(ff==="BULL"&&!(s.chg>0))return;if(ff==="BEAR"&&!(s.chg<0))return;if(ff==="GAPS"&&Math.abs(s.gap)<1)return;(secs[s.sector]=secs[s.sector]||[]).push(s)});
 var items=Object.keys(secs).map(function(k){var arr=secs[k].map(function(s){return{s:s,v:hasT?Math.max(s.turnover_cr,.05):1}}).sort(function(a,b){return b.v-a.v});return{name:k,arr:arr,v:arr.reduce(function(a,i){return a+i.v},0)}}).sort(function(a,b){return b.v-a.v});
 var blocks=layout(items,{x:0,y:0,w:W,h:H});
 blocks.forEach(function(b){var hd=b.h>46&&b.w>70?16:0;html+='<div class="sechead" style="left:'+b.x+'px;top:'+b.y+'px;width:'+b.w+'px">'+(hd?b.i.name:"")+'</div>';
  var inner=layout(b.i.arr,{x:b.x+1,y:b.y+hd,w:b.w-2,h:b.h-hd-1});
  inner.forEach(function(q){var s=q.i.s,big=q.w>46&&q.h>28;html+='<div class="cell" data-sym="'+s.symbol+'" title="'+s.symbol+'  '+f(s.chg)+'%  '+Math.round(s.turnover_cr)+' cr" style="left:'+q.x+'px;top:'+q.y+'px;width:'+q.w+'px;height:'+q.h+'px;background:'+colour(s.chg)+'">'+(big?'<b>'+s.symbol+'</b><br>'+f(s.chg)+'%'+(Math.abs(s.gap)>=1&&q.h>40?'<br><span class="gap">GAP '+(s.gap>0?"UP":"DN")+'</span>':""):(q.w>28&&q.h>14?'<b style="font-size:9.5px">'+s.symbol+'</b>':""))+'</div>'})});
 el.innerHTML=html;document.getElementById("showing").textContent=sel?"Showing "+sel+" - click the sector again to show all":"Showing all sectors";document.getElementById("mapnote").textContent=hasT?"size = turnover":"size = equal (no turnover data yet)"}
document.getElementById("tabs").addEventListener("click",function(e){var b=e.target.closest("button");if(!b)return;mode=b.getAttribute("data-m");[].forEach.call(this.querySelectorAll("button"),function(x){x.className=x===b?"on":""});render()});
document.getElementById("secs").addEventListener("click",function(e){var r=e.target.closest(".srow");if(!r)return;var s=r.getAttribute("data-s");sel=sel===s?null:s;render()});
document.getElementById("map").addEventListener("click",function(e){var c2=e.target.closest(".cell");if(c2)location.href="/stock-analysis?symbol="+encodeURIComponent(c2.getAttribute("data-sym"))});
document.getElementById("fbar").addEventListener("click",function(e){var b=e.target.closest("button");if(!b)return;ff=b.getAttribute("data-f");[].forEach.call(this.querySelectorAll("button"),function(x){x.className=x===b?"on":""});drawMap()});
function minis(){if(!D||!D.ok||!window.LightweightCharts)return;var box=document.getElementById("minis");
 D.most_active.forEach(function(sym){var st=D.stocks.filter(function(x){return x.symbol===sym})[0]||{},id="mini_"+sym;
  if(!document.getElementById(id)){box.insertAdjacentHTML("beforeend",'<div class="mini" id="'+id+'"><div class="t"><a class="nav" href="/stock-analysis?symbol='+sym+'">'+sym+'</a><span id="'+id+'_c"></span></div><div class="ch" id="'+id+'_ch"></div></div>')}
  document.getElementById(id+"_c").innerHTML='<span class="'+c(st.chg)+'">'+f(st.chg)+'%</span> <span class="sub">'+(st.ltp||"")+'</span>';
  fetch("/api/stock-day-chart?symbol="+encodeURIComponent(sym),{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){if(!d.ok)return;var ch=charts[sym];
   if(!ch){var chart=LightweightCharts.createChart(document.getElementById(id+"_ch"),{autoSize:true,layout:{background:{color:"#0f1729"},textColor:"#8ea0bd"},grid:{vertLines:{visible:false},horzLines:{color:"#1d2842"}},timeScale:{timeVisible:true,secondsVisible:false,borderColor:"#27334d"},rightPriceScale:{borderColor:"#27334d"}});
    ch={chart:chart,series:chart.addCandlestickSeries({upColor:"#2ecc71",downColor:"#ff6363",borderUpColor:"#2ecc71",borderDownColor:"#ff6363",wickUpColor:"#2ecc71",wickDownColor:"#ff6363"})};charts[sym]=ch}
   ch.series.setData(d.candles.map(function(x){return{time:x.t,open:x.o,high:x.h,low:x.l,close:x.c}}));ch.chart.timeScale().fitContent()}).catch(function(){})})}
setInterval(minis,60000);
window.addEventListener("resize",function(){if(D&&D.ok)drawMap()});load();setInterval(load,30000);
</script></body></html>
"""
