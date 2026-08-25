from __future__ import annotations
import csv
from pathlib import Path
from urllib.parse import parse_qs

ROOT=Path(__file__).resolve().parent
BASE=ROOT/"data"/"chart_history"

def _f(v):
    try:return float(v)
    except:return 0.0

def _load(day):
    p=BASE/day/"market_watch_1m.csv"
    if not p.exists(): return []
    with p.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def _svg(points,width=1000,height=420):
    if not points:
        return f'<svg viewBox="0 0 {width} {height}" width="100%" height="100%"><text x="30" y="50" fill="#8ea0bd" font-size="18">No chart data</text></svg>'
    vals=[_f(p.get("from_open_pct")) for p in points]
    mn=min(vals); mx=max(vals)
    if mx==mn: mx+=1; mn-=1
    pad=(mx-mn)*0.12
    mn-=pad; mx+=pad
    left,right,top,bottom=54,width-18,18,height-36
    def X(i): return left+(right-left)*(i/(len(points)-1 if len(points)>1 else 1))
    def Y(v): return bottom-(bottom-top)*((v-mn)/(mx-mn))
    pts=" ".join(f"{X(i):.1f},{Y(v):.1f}" for i,v in enumerate(vals))
    last=vals[-1]
    stroke="#17c964" if last>=0 else "#f31260"
    grid=[]
    for i in range(5):
        y=top+(bottom-top)*i/4
        value=mx-(mx-mn)*i/4
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#27334d" stroke-width="1"/>')
        grid.append(f'<text x="6" y="{y+4:.1f}" fill="#8ea0bd" font-size="12">{value:.2f}%</text>')
    zero=""
    if mn<=0<=mx:
        zy=Y(0)
        zero=f'<line x1="{left}" y1="{zy:.1f}" x2="{right}" y2="{zy:.1f}" stroke="#8ea0bd" stroke-dasharray="5 5"/>'
    labels=[]
    for frac in (0,.25,.5,.75,1):
        idx=min(len(points)-1,round((len(points)-1)*frac))
        t=points[idx].get("time","")
        x=X(idx)
        labels.append(f'<text x="{x:.1f}" y="{height-10}" fill="#8ea0bd" font-size="12" text-anchor="middle">{t}</text>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="100%" preserveAspectRatio="none">'
        + "".join(grid)+zero
        + f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'
        + "".join(labels)
        + '</svg>'
    )

def symbols_payload(day):
    by={}
    for r in _load(day):
        sym=str(r.get("symbol") or "").upper()
        if sym:
            by[sym]={
                "symbol":sym,
                "sector":r.get("sector",""),
                "last_ltp":_f(r.get("ltp")),
                "last_from_open_pct":_f(r.get("from_open_pct")),
                "minute":r.get("minute",""),
            }
    return {"day":day,"symbols":sorted(by.values(),key=lambda x:x["last_from_open_pct"],reverse=True)}

def chart_payload(day,symbol):
    symbol=symbol.upper().strip()
    rows=[r for r in _load(day) if str(r.get("symbol") or "").upper()==symbol]
    points=[{
        "time":r.get("minute"),
        "ltp":_f(r.get("ltp")),
        "from_open_pct":_f(r.get("from_open_pct")),
        "range_position_pct":_f(r.get("range_position_pct")),
    } for r in rows]
    meta={}
    if rows:
        z=rows[-1]
        meta={
            "open_0915":_f(z.get("open_0915")),
            "last_ltp":_f(z.get("ltp")),
            "last_from_open_pct":_f(z.get("from_open_pct")),
            "day_high":_f(z.get("day_high")),
            "day_low":_f(z.get("day_low")),
            "sector":z.get("sector",""),
        }
    return {"day":day,"symbol":symbol,"points":points,"meta":meta,"svg":_svg(points)}

def parse_query(raw):
    if "?" not in raw:return {}
    return {k:(v[0] if v else "") for k,v in parse_qs(raw.split("?",1)[1]).items()}

STOCK_CHART_HTML=r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>APlus Stock Charts</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#17c964;--red:#f31260;--cyan:#22d3ee}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}.header{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.title{font-size:23px;font-weight:800}.sub{font-size:12px;color:var(--muted)}.nav{display:flex;gap:7px;flex-wrap:wrap;padding:10px 20px;border-bottom:1px solid var(--line)}.nav a,.toolbar button,.toolbar select,.toolbar input{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:9px;padding:8px 11px;text-decoration:none;font-weight:650}.toolbar{display:flex;gap:8px;flex-wrap:wrap;padding:12px 20px}.grid{display:grid;grid-template-columns:300px 1fr;gap:12px;padding:0 20px 20px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.list{max-height:72vh;overflow:auto}.stock{padding:9px 11px;border-bottom:1px solid var(--line);cursor:pointer;display:flex;justify-content:space-between}.stock:hover,.stock.sel{background:#18243b}.up{color:var(--green)}.down{color:var(--red)}#chart{height:540px;width:100%;padding:10px}.meta{padding:10px 14px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);display:flex;gap:18px;flex-wrap:wrap}.gallery{display:none;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:0 20px 20px}.mini{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:9px;cursor:pointer}.minichart{height:110px}.minihead{display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px}@media(max-width:900px){.grid{grid-template-columns:1fr;padding:0 10px 12px}.list{max-height:220px}.gallery{grid-template-columns:repeat(2,minmax(0,1fr));padding:0 10px 12px}#chart{height:390px}}
</style></head><body>
<div class="header"><div><div class="title">APlus Stock Charts / Day Replay</div><div class="sub">All F&O stocks • server-rendered SVG charts</div></div><div class="sub" id="status">Loading...</div></div>
<div class="nav"><a href="/">LIVE TRADING</a><a href="/fno-market-watch">F&amp;O MARKET WATCH</a><a href="/sector-performance">SECTOR PERFORMANCE</a><a href="/opening-structure">OPENING STRUCTURE</a><a href="/stock-charts">STOCK CHARTS</a></div>
<div class="toolbar"><input type="date" id="day"><select id="sector"><option value="">All sectors</option></select><input id="search" placeholder="Search symbol"><button id="detailBtn">Detail</button><button id="galleryBtn">Gallery</button></div>
<div class="grid" id="detailView"><div class="panel"><div class="list" id="list"></div></div><div class="panel"><div id="chart"></div><div class="meta" id="meta"></div></div></div><div class="gallery" id="gallery"></div>
<script>
let symbols=[],selected="";const q=s=>document.querySelector(s);function cls(v){return Number(v)>=0?"up":"down"}
async function loadSymbols(){let d=q("#day").value,r=await fetch("/api/stock-chart-symbols?day="+d+"&ts="+Date.now()),j=await r.json();symbols=j.symbols||[];let secs=[...new Set(symbols.map(x=>x.sector).filter(Boolean))].sort();q("#sector").innerHTML='<option value="">All sectors</option>'+secs.map(s=>`<option>${s}</option>`).join("");renderList();if(!selected&&symbols.length)await selectStock(symbols[0].symbol);q("#status").textContent=`${symbols.length} stocks • ${j.day||d}`}
function filtered(){let s=q("#search").value.trim().toUpperCase(),sec=q("#sector").value;return symbols.filter(x=>(!s||x.symbol.includes(s))&&(!sec||x.sector===sec))}
function renderList(){q("#list").innerHTML=filtered().map(x=>`<div class="stock ${x.symbol===selected?'sel':''}" onclick="selectStock('${x.symbol}')"><b>${x.symbol}</b><span class="${cls(x.last_from_open_pct)}">${Number(x.last_from_open_pct||0).toFixed(2)}%</span></div>`).join("")}
async function selectStock(sym){selected=sym;renderList();let d=q("#day").value,r=await fetch(`/api/stock-chart?day=${d}&symbol=${encodeURIComponent(sym)}&ts=${Date.now()}`),j=await r.json();q("#chart").innerHTML=j.svg||"<div class='sub'>No chart</div>";let m=j.meta||{};q("#meta").innerHTML=`<b>${sym}</b><span>Points ${(j.points||[]).length}</span><span>Open ${m.open_0915??'-'}</span><span>Last ${m.last_ltp??'-'}</span><span>From open ${Number(m.last_from_open_pct||0).toFixed(2)}%</span><span>High ${m.day_high??'-'}</span><span>Low ${m.day_low??'-'}</span>`}
async function showGallery(){q("#detailView").style.display="none";q("#gallery").style.display="grid";let list=filtered(),d=q("#day").value;q("#gallery").innerHTML=list.map(x=>`<div class="mini" onclick="selectStock('${x.symbol}');showDetail()"><div class="minihead"><b>${x.symbol}</b><span class="${cls(x.last_from_open_pct)}">${Number(x.last_from_open_pct||0).toFixed(2)}%</span></div><div class="minichart" id="m_${x.symbol.replace(/[^A-Za-z0-9]/g,'_')}"></div></div>`).join("");for(const x of list){let r=await fetch(`/api/stock-chart?day=${d}&symbol=${encodeURIComponent(x.symbol)}`),j=await r.json(),e=document.getElementById("m_"+x.symbol.replace(/[^A-Za-z0-9]/g,'_'));if(e)e.innerHTML=j.svg||""}}
function showDetail(){q("#detailView").style.display="grid";q("#gallery").style.display="none"}q("#detailBtn").onclick=showDetail;q("#galleryBtn").onclick=showGallery;q("#search").oninput=renderList;q("#sector").onchange=renderList;q("#day").onchange=()=>{selected="";loadSymbols()};q("#day").value="2026-08-20";loadSymbols();
</script></body></html>"""
