# APLUS_GLOBAL_STOCK_SEARCH_V1_MAIN
from __future__ import annotations
from paper_trade_history_dashboard import history_html, history_payload, days_payload

from pathlib import Path
from datetime import datetime
import csv
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from stock_chart_dashboard_module import STOCK_CHART_HTML, symbols_payload, chart_payload, parse_query

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
HOST = "0.0.0.0"
PORT = 8765

MAIN_MOBILE_CSS = '\n<style id="aplus-mobile-css">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n@media(max-width:760px){\n  body{font-size:14px!important;overflow-x:hidden}\n  #aplus-main-nav{position:sticky!important;top:0!important;z-index:9999!important;padding:8px!important;gap:6px!important;overflow-x:auto!important;flex-wrap:nowrap!important;-webkit-overflow-scrolling:touch}\n  #aplus-main-nav a{flex:0 0 auto!important;padding:9px 11px!important;font-size:11px!important;white-space:nowrap!important}\n  .header{padding:12px 14px!important;gap:10px!important;align-items:flex-start!important}\n  .brandrow{gap:8px!important}.aplus-logo{width:38px!important;height:38px!important}\n  .title{font-size:18px!important}.sub{font-size:10px!important}\n  .grid,.cards{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:8px!important;padding:10px!important}\n  .card{padding:10px!important;border-radius:10px!important}\n  .label{font-size:10px!important}.value{font-size:18px!important}\n  .filterbar,.toolbar,.tabs{padding:0 10px 10px!important;gap:6px!important;overflow-x:auto!important;white-space:nowrap!important;flex-wrap:nowrap!important}\n  .tradefilter,.toolbar button,.toolbar select,.tab{padding:8px 10px!important;font-size:11px!important;flex:0 0 auto!important}\n  .tablewrap{padding:0 8px 12px!important;overflow-x:auto!important;-webkit-overflow-scrolling:touch}\n  table{min-width:980px!important}\n  th,td{padding:8px!important;font-size:11px!important}\n  .grid{grid-template-columns:1fr!important}\n  .crisp-footer{grid-template-columns:1fr!important;padding:14px!important;gap:10px!important;text-align:center!important}\n  .cf-copy{text-align:center!important}.cf-title{font-size:17px!important}\n  .watermark{font-size:34px!important}\n}\n</style>\n'


def _mobileize_html(html, host=None):
    if not isinstance(html, str):
        return html
    out = html
    if 'id="aplus-mobile-css"' not in out:
        out = out.replace("</head>", MAIN_MOBILE_CSS + "</head>", 1)
    if host:
        out = out.replace("http://127.0.0.1:8766", f"http://{host}:8766")
    return out

def _num(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default

def _load_trades():
    p_json = REPORTS / "paper_trades_latest.json"
    p_csv = REPORTS / "paper_trades.csv"
    if p_json.is_file():
        try:
            obj = json.loads(p_json.read_text(encoding="utf-8"))
            trades = obj.get("paper_trades") or obj.get("trades") or []
            return [t for t in trades if isinstance(t, dict)]
        except Exception:
            pass
    if p_csv.is_file():
        with p_csv.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    return []

def _status(t):
    return str(t.get("status") or "").upper()

def _pnl(t):
    return _num(t.get("net_pnl") if t.get("net_pnl") not in (None, "") else t.get("pnl"))

def _capital(t):
    return _num(t.get("capital_deployed") or t.get("capital"))

def _return_pct(t):
    if t.get("return_percent") not in (None, ""):
        return _num(t.get("return_percent"))
    cap = _capital(t)
    return (_pnl(t) / cap * 100.0) if cap else 0.0

def _time(v):
    s = str(v or "")
    if "T" in s:
        return s.split("T", 1)[1].split("+", 1)[0].split(".", 1)[0]
    return s or "-"

def _load_fno_market_watch():
    path = REPORTS / "fno_market_watch_latest.json"
    if not path.is_file():
        return {"generated_at": "", "count": 0, "rows": [], "sectors": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"generated_at": "", "count": 0, "rows": [], "sectors": []}


FNO_MARKET_WATCH_HTML = '<!doctype html><html><head><meta charset="utf-8"><title>APlus F&O Market Watch</title>\n<style>:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}.title{font-size:24px;font-weight:750}.sub{color:var(--muted);font-size:12px;margin-top:4px}.toolbar{padding:14px 24px;display:flex;gap:8px;flex-wrap:wrap}.toolbar button,.toolbar select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 12px;font-weight:600}.toolbar button{cursor:pointer}.active{border-color:var(--green)!important;background:#173527!important;color:#9ff0bd!important}.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;padding:0 24px 14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.label{font-size:11px;color:var(--muted)}.value{font-size:20px;font-weight:750;margin-top:5px}.tablewrap{padding:0 24px 26px;overflow:auto}table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:9px 10px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}th{color:var(--muted);background:#0f1729;position:sticky;top:0}.right{text-align:right}.up{color:var(--green);font-weight:700}.down{color:var(--red);font-weight:700}a{color:#7dd3fc;text-decoration:none}.footer{padding:18px;text-align:center;color:var(--muted);border-top:1px solid var(--line)}@media(max-width:1100px){.cards{grid-template-columns:repeat(2,1fr)}}</style></head><body>\n<div class="header"><div><div class="title">APlus F&O Market Watch</div><div class="sub">Full F&O universe • 09:15 Open → Now • Previous Close • High/Low • Gap • Sector</div></div><div style="text-align:right"><a href="/">← Live Trading Terminal</a><div id="updated" class="sub">Waiting for scanner data...</div></div></div>\n<div style="padding:12px 24px;display:flex;gap:8px">\n  <a href="/fno-market-watch" style="padding:8px 14px;border-radius:9px;border:1px solid #22d3ee;color:#9ffcff;background:#0f2730;font-weight:700;text-decoration:none">Market Watch</a>\n  <a href="/sector-performance" style="padding:8px 14px;border-radius:9px;border:1px solid #27334d;color:#e7eefc;background:#121a2d;font-weight:700;text-decoration:none">Sector Performance</a>\n</div>\n<div class="cards"><div class="card"><div class="label">F&O Stocks</div><div class="value" id="count">-</div></div><div class="card"><div class="label">Advancing from Open</div><div class="value up" id="adv">-</div></div><div class="card"><div class="label">Declining from Open</div><div class="value down" id="dec">-</div></div><div class="card"><div class="label">Top From Open</div><div class="value up" id="topup">-</div></div><div class="card"><div class="label">Bottom From Open</div><div class="value down" id="topdown">-</div></div></div>\n<div class="toolbar"><button id="bALL" class="active" onclick="setMode(\'ALL\')">All</button><button id="bGAIN" onclick="setMode(\'GAIN\')">Top Gainers</button><button id="bLOSS" onclick="setMode(\'LOSS\')">Top Losers</button><button id="bUP" onclick="setMode(\'UP\')">Strong Up ≥1%</button><button id="bDOWN" onclick="setMode(\'DOWN\')">Strong Down ≤−1%</button><select id="sector" onchange="render()"><option value="ALL">All Sectors</option></select><select id="basis" onchange="render()"><option value="from_open_pct">Sort: From 09:15 Open %</option><option value="from_prev_close_pct">Sort: From Prev Close %</option><option value="gap_pct">Sort: Gap %</option></select><input id="stockSearch" type="text" placeholder="Search stock..." oninput="render()" style="min-width:190px;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 12px;font-weight:600;outline:none"><button onclick="document.getElementById('stockSearch').value='';render()">Clear Search</button><span class="sub" id="shown"></span></div>\n<div class="tablewrap"><table><thead><tr><th>Symbol</th><th>Sector</th><th class="right">9:15 Open</th><th class="right">LTP</th><th class="right">Prev Close</th><th class="right">Gap %</th><th class="right">From Open %</th><th class="right">From Prev Close %</th><th class="right">Day High</th><th class="right">Day Low</th><th class="right">Range Pos %</th><th>Direction</th></tr></thead><tbody id="rows"></tbody></table></div>\n<div class="footer">APlus Live Trading Terminal — Developed by Darpan Bobhate</div>\n<script>let data=[],mode=\'ALL\';const money=n=>\'₹\'+Number(n||0).toLocaleString(\'en-IN\',{maximumFractionDigits:2});const pct=n=>(Number(n)>=0?\'+\':\'\')+Number(n||0).toFixed(2)+\'%\';function setMode(m){mode=m;document.querySelectorAll(\'.toolbar button\').forEach(x=>x.classList.remove(\'active\'));document.getElementById(\'b\'+m).classList.add(\'active\');render()}function render(){let a=[...data],q=((document.getElementById('stockSearch')||{}).value||'').trim().toUpperCase();if(q)a=a.filter(x=>String(x.symbol||'').toUpperCase().includes(q)||String(x.sector||'').toUpperCase().includes(q));sec=sector.value,b=basis.value;if(sec!==\'ALL\')a=a.filter(x=>x.sector===sec);if(mode===\'GAIN\')a=a.filter(x=>x[b]>0).sort((x,y)=>y[b]-x[b]).slice(0,30);else if(mode===\'LOSS\')a=a.filter(x=>x[b]<0).sort((x,y)=>x[b]-y[b]).slice(0,30);else if(mode===\'UP\')a=a.filter(x=>x.from_open_pct>=1).sort((x,y)=>y.from_open_pct-x.from_open_pct);else if(mode===\'DOWN\')a=a.filter(x=>x.from_open_pct<=-1).sort((x,y)=>x.from_open_pct-y.from_open_pct);else a.sort((x,y)=>y[b]-x[b]);shown.textContent=\'Showing \'+a.length+\' of \'+data.length+\' stocks\';rows.innerHTML=a.map(x=>`<tr><td><b>${x.symbol}</b></td><td>${x.sector||\'UNCLASSIFIED\'}</td><td class="right">${money(x.open_0915)}</td><td class="right">${money(x.ltp)}</td><td class="right">${money(x.previous_close)}</td><td class="right ${x.gap_pct>=0?\'up\':\'down\'}">${pct(x.gap_pct)}</td><td class="right ${x.from_open_pct>=0?\'up\':\'down\'}">${pct(x.from_open_pct)}</td><td class="right ${x.from_prev_close_pct>=0?\'up\':\'down\'}">${pct(x.from_prev_close_pct)}</td><td class="right">${money(x.day_high)}</td><td class="right">${money(x.day_low)}</td><td class="right">${Number(x.range_position_pct||0).toFixed(1)}</td><td class="${x.direction===\'UP\'?\'up\':x.direction===\'DOWN\'?\'down\':\'\'}">${x.direction===\'UP\'?\'▲\':x.direction===\'DOWN\'?\'▼\':\'•\'} ${x.direction}</td></tr>`).join(\'\')}async function load(){const r=await fetch(\'/api/fno-market-watch?ts=\'+Date.now());const d=await r.json();data=d.rows||[];count.textContent=data.length;adv.textContent=data.filter(x=>x.from_open_pct>0).length;dec.textContent=data.filter(x=>x.from_open_pct<0).length;if(data.length){let u=[...data].sort((a,b)=>b.from_open_pct-a.from_open_pct)[0],dn=[...data].sort((a,b)=>a.from_open_pct-b.from_open_pct)[0];topup.textContent=u.symbol+\' \'+pct(u.from_open_pct);topdown.textContent=dn.symbol+\' \'+pct(dn.from_open_pct)}updated.textContent=d.generated_at?\'Updated \'+String(d.generated_at).slice(11,19):\'Waiting for scanner data...\';const old=sector.value;const secs=[...new Set(data.map(x=>x.sector||\'UNCLASSIFIED\'))].sort();sector.innerHTML=\'<option value="ALL">All Sectors</option>\'+secs.map(x=>`<option value="${x}">${x}</option>`).join(\'\');if(old===\'ALL\'||secs.includes(old))sector.value=old;render()}load();setInterval(load,5000)</script><a href="/fno-market-watch" style="position:fixed;right:22px;bottom:22px;z-index:999;background:#17c964;color:#04130a;text-decoration:none;font-weight:800;padding:11px 16px;border-radius:12px;box-shadow:0 5px 24px #0008">F&amp;O MARKET WATCH</a><a href="/opening-structure" style="position:fixed;left:22px;bottom:22px;z-index:9998;background:#0f2730;color:#9ffcff;text-decoration:none;font-weight:800;padding:10px 14px;border:1px solid #22d3ee;border-radius:10px">OPENING STRUCTURE</a></body></html>'

SECTOR_PERFORMANCE_HTML = '<!doctype html>\n<html><head><meta charset="utf-8"><title>APlus Sector Performance</title>\n<style>\n:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d;--cyan:#22d3ee}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}\n.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}\n.title{font-size:24px;font-weight:750}.sub{color:var(--muted);font-size:12px;margin-top:4px}\n.tabs{padding:12px 24px;display:flex;gap:8px}.tab{padding:8px 14px;border-radius:9px;border:1px solid var(--line);color:var(--text);background:var(--panel);font-weight:700;text-decoration:none}.tab.active{border-color:var(--cyan);color:#9ffcff;background:#0f2730}\n.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;padding:0 24px 14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.label{font-size:11px;color:var(--muted)}.value{font-size:20px;font-weight:750;margin-top:5px}\n.grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(500px,.85fr);gap:14px;padding:0 24px 20px}\n.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}.boxtitle{font-size:18px;font-weight:750;margin-bottom:10px}\n.chart{height:520px;overflow:auto;padding-right:8px}.barrow{display:grid;grid-template-columns:180px 1fr 72px;align-items:center;gap:10px;margin:7px 0;cursor:pointer}.barlabel{font-size:12px;text-align:right}.track{height:13px;background:#0f1729;border-radius:4px;position:relative;overflow:hidden}.fill{height:100%;border-radius:4px}.fill.up{background:rgba(23,201,100,.75)}.fill.down{background:rgba(243,18,96,.75)}.barval{font-size:12px;font-weight:700}.up{color:var(--green)}.down{color:var(--red)}\n.tablewrap{max-height:520px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}th{position:sticky;top:0;background:#0f1729;color:var(--muted);text-align:left}.right{text-align:right}.ltp{font-weight:850;color:#eaffff;text-shadow:0 0 8px rgba(34,211,238,.7)}\n.footer{padding:18px;text-align:center;color:var(--muted);border-top:1px solid var(--line)}\n@media(max-width:1200px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}}\n</style></head><body>\n<div class="header"><div><div class="title">APlus F&O Market Watch</div><div class="sub">Sector Performance • all % calculations from 09:15 Open only</div></div><div style="text-align:right"><a href="/" style="color:#7dd3fc;text-decoration:none">← Live Trading Terminal</a><div id="updated" class="sub">Waiting...</div></div></div>\n<div class="cards">\n<div class="card"><div class="label">F&O Stocks</div><div id="cnt" class="value">-</div></div>\n<div class="card"><div class="label">Advancing from 09:15 Open</div><div id="adv" class="value up">-</div></div>\n<div class="card"><div class="label">Declining from 09:15 Open</div><div id="dec" class="value down">-</div></div>\n<div class="card"><div class="label">Top from 09:15 Open</div><div id="topup" class="value up">-</div></div>\n<div class="card"><div class="label">Bottom from 09:15 Open</div><div id="topdn" class="value down">-</div></div>\n</div>\n<div class="tabs"><a class="tab" href="/fno-market-watch">Market Watch</a><a class="tab active" href="/sector-performance">Sector Performance</a></div>\n<div class="grid">\n  <div class="box">\n    <div class="boxtitle">Sector Performance - from 09:15 Open</div>\n    <div class="sub">Sector % = average move of its F&O stocks from each stock\'s own 09:15 open.</div>\n    <div class="tablewrap" style="max-height:520px">\n      <table>\n        <thead><tr>\n          <th>Sector</th><th class="right">% from 09:15</th><th class="right">Stocks</th>\n          <th class="right">Adv</th><th class="right">Dec</th><th>Top Stock</th><th>Bottom Stock</th>\n        </tr></thead>\n        <tbody id="sectorSummary"></tbody>\n      </table>\n    </div>\n    <div class="sub">Click any sector row to view all constituent stocks.</div>\n  </div>\n  <div class="box">\n    <div class="boxtitle" id="stockTitle">Sector Stocks</div>\n    <div class="tablewrap"><table><thead><tr>\n      <th>Symbol</th><th>Sector</th><th class="right">% from 09:15 Open</th><th class="right">LTP</th><th class="right">09:15 Open</th><th class="right">High</th><th class="right">Low</th>\n    </tr></thead><tbody id="sectorStocks"></tbody></table></div>\n  </div>\n</div>\n<div class="footer">APlus Live Trading Terminal — Developed by Darpan Bobhate</div>\n<script>\nlet data=[],selectedSector=null;\nconst money=n=>\'₹\'+Number(n||0).toLocaleString(\'en-IN\',{maximumFractionDigits:2});\nconst pct=n=>(Number(n)>=0?\'+\':\'\')+Number(n||0).toFixed(2)+\'%\';\n\nfunction aggregateSectors(){\n const m={};\n data.forEach(x=>{\n   const s=x.sector||\'Other/Industrial\';\n   if(!m[s])m[s]={sector:s,sum:0,count:0,adv:0,dec:0,stocks:[]};\n   const mv=Number(x.from_open_pct||0);\n   m[s].sum+=mv;m[s].count++;\n   if(mv>0)m[s].adv++; else if(mv<0)m[s].dec++;\n   m[s].stocks.push(x);\n });\n return Object.values(m).map(x=>{\n   x.stocks.sort((a,b)=>Number(b.from_open_pct||0)-Number(a.from_open_pct||0));\n   return {sector:x.sector,move:x.count?x.sum/x.count:0,count:x.count,adv:x.adv,dec:x.dec,\n           top:x.stocks[0]||null,bottom:x.stocks[x.stocks.length-1]||null};\n }).sort((a,b)=>b.move-a.move);\n}\nfunction renderBars(){\n const a=aggregateSectors();\n sectorSummary.innerHTML=a.map(x=>`<tr data-sector="${x.sector.replace(/"/g,\'&quot;\')}" style="cursor:pointer">\n   <td><b>${x.sector}</b></td>\n   <td class="right ${x.move>=0?\'up\':\'down\'}"><b>${pct(x.move)}</b></td>\n   <td class="right">${x.count}</td>\n   <td class="right up">${x.adv}</td>\n   <td class="right down">${x.dec}</td>\n   <td class="${x.top&&Number(x.top.from_open_pct)>=0?\'up\':\'down\'}">${x.top?x.top.symbol+\' \'+pct(x.top.from_open_pct):\'-\'}</td>\n   <td class="${x.bottom&&Number(x.bottom.from_open_pct)>=0?\'up\':\'down\'}">${x.bottom?x.bottom.symbol+\' \'+pct(x.bottom.from_open_pct):\'-\'}</td>\n </tr>`).join(\'\');\n document.querySelectorAll(\'#sectorSummary tr\').forEach(el=>el.onclick=()=>selectSector(el.dataset.sector));\n if(!selectedSector && a.length)selectSector(a[0].sector);\n}\nfunction selectSector(s){selectedSector=s;renderStocks();}\nfunction renderStocks(){\n stockTitle.textContent=(selectedSector||\'Sector\')+\' Stocks\';\n const a=data.filter(x=>(x.sector||\'Other/Industrial\')===selectedSector).sort((x,y)=>y.from_open_pct-x.from_open_pct);\n sectorStocks.innerHTML=a.map(x=>`<tr>\n <td><b>${x.symbol}</b></td><td>${x.sector||\'Other/Industrial\'}</td>\n <td class="right ${x.from_open_pct>=0?\'up\':\'down\'}">${pct(x.from_open_pct)}</td>\n <td class="right ltp">${money(x.ltp)}</td><td class="right">${money(x.open_0915)}</td>\n <td class="right">${money(x.day_high)}</td><td class="right">${money(x.day_low)}</td></tr>`).join(\'\');\n}\nasync function load(){\n const r=await fetch(\'/api/fno-market-watch?ts=\'+Date.now());const d=await r.json();data=d.rows||[];\n cnt.textContent=data.length;adv.textContent=data.filter(x=>x.from_open_pct>0).length;dec.textContent=data.filter(x=>x.from_open_pct<0).length;\n if(data.length){const u=[...data].sort((a,b)=>b.from_open_pct-a.from_open_pct)[0],dn=[...data].sort((a,b)=>a.from_open_pct-b.from_open_pct)[0];topup.textContent=u.symbol+\' \'+pct(u.from_open_pct);topdn.textContent=dn.symbol+\' \'+pct(dn.from_open_pct);}\n updated.textContent=d.generated_at?\'Updated \'+String(d.generated_at).slice(11,19):\'Waiting...\';\n renderBars();if(selectedSector)renderStocks();\n}\nload();setInterval(load,5000);\n</script></body></html>'

OPENING_STRUCTURE_HTML = '<!doctype html>\n<html><head><meta charset="utf-8"><title>APlus Opening Structure</title>\n<style>\n:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d;--cyan:#22d3ee}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}\n.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}\n.title{font-size:24px;font-weight:800}.sub{color:var(--muted);font-size:12px;margin-top:4px}\n.tabs{padding:12px 24px;display:flex;gap:8px;flex-wrap:wrap}.tab{padding:8px 14px;border-radius:9px;border:1px solid var(--line);color:var(--text);background:var(--panel);font-weight:700;text-decoration:none}.tab.active{border-color:var(--cyan);color:#9ffcff;background:#0f2730}\n.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;padding:0 24px 14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.label{font-size:11px;color:var(--muted)}.value{font-size:20px;font-weight:800;margin-top:5px}\n.toolbar{padding:0 24px 12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}\nbutton,select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 12px;font-weight:700}\nbutton{cursor:pointer}.activeBtn{border-color:var(--green);background:#173527;color:#9ff0bd}\n.tablewrap{padding:0 24px 24px;overflow:auto}table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line)}\nth,td{padding:9px 10px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}th{color:var(--muted);background:#0f1729;position:sticky;top:0}.right{text-align:right}\n.up{color:var(--green);font-weight:750}.down{color:var(--red);font-weight:750}.neutral{color:var(--muted)}\n.badge{display:inline-block;padding:3px 8px;border-radius:999px;font-weight:800}.bull{background:#173527;color:#9ff0bd}.bear{background:#3c1724;color:#ff9bbb}.watch{background:#243049;color:#bdd0ef}\n.ltp{font-weight:900;color:#eaffff;text-shadow:0 0 8px rgba(34,211,238,.72)}\n.footer{padding:18px;text-align:center;color:var(--muted);border-top:1px solid var(--line)}\n@media(max-width:1200px){.cards{grid-template-columns:repeat(3,1fr)}}\n</style></head><body>\n<div class="header">\n <div><div class="title">APlus Opening Structure Scanner</div>\n <div class="sub">Open≈Low / Open≈High • confirmation from 09:15 movement + sector alignment • PAPER / RESEARCH ONLY</div></div>\n <div style="text-align:right"><a href="/" style="color:#7dd3fc;text-decoration:none">← Live Trading Terminal</a><div id="updated" class="sub">Waiting...</div></div>\n</div>\n<div class="cards">\n <div class="card"><div class="label">F&O Stocks</div><div id="cnt" class="value">-</div></div>\n <div class="card"><div class="label">Open≈Low</div><div id="ol" class="value up">-</div></div>\n <div class="card"><div class="label">Open≈High</div><div id="oh" class="value down">-</div></div>\n <div class="card"><div class="label">Open≈Low Confirmed</div><div id="olc" class="value up">-</div></div>\n <div class="card"><div class="label">Open≈High Confirmed</div><div id="ohc" class="value down">-</div></div>\n <div class="card"><div class="label">Qualified CE / PE</div><div id="qp" class="value">-</div></div>\n</div>\n<div class="tabs">\n <a class="tab" href="/fno-market-watch">Market Watch</a>\n <a class="tab" href="/sector-performance">Sector Performance</a>\n <a class="tab active" href="/opening-structure">Opening Structure</a>\n</div>\n<div class="toolbar">\n <button id="bALL" class="activeBtn" onclick="setMode(\'ALL\')">All</button>\n <button id="bOL" onclick="setMode(\'OL\')">Open≈Low</button>\n <button id="bOH" onclick="setMode(\'OH\')">Open≈High</button>\n <button id="bOLC" onclick="setMode(\'OLC\')">Open≈Low Confirmed</button>\n <button id="bOHC" onclick="setMode(\'OHC\')">Open≈High Confirmed</button>\n <select id="sectorFilter" onchange="render()"><option value="ALL">All Sectors</option></select>\n <span class="sub">Tolerance: max ₹0.05 or 0.05% of Open</span>\n <span class="sub" id="shown"></span>\n</div>\n<div class="tablewrap"><table>\n<thead><tr>\n <th>Symbol</th><th>Sector</th><th>Structure</th><th class="right">Open</th><th class="right">LTP</th>\n <th class="right">High</th><th class="right">Low</th><th class="right">Open→Low Dist %</th>\n <th class="right">Open→High Dist %</th><th class="right">% from 09:15</th><th class="right">Sector %</th>\n <th>Confirmation</th><th>Bias</th>\n</tr></thead><tbody id="rows"></tbody></table></div>\n<div class="footer">APlus Live Trading Terminal — Developed by Darpan Bobhate</div>\n<script>\nlet data=[],mode=\'ALL\',sectorPerf={};\nconst money=n=>\'₹\'+Number(n||0).toLocaleString(\'en-IN\',{maximumFractionDigits:2});\nconst pct=n=>(Number(n)>=0?\'+\':\'\')+Number(n||0).toFixed(2)+\'%\';\n\nfunction buildSectorPerf(){\n const m={};data.forEach(x=>{const s=x.sector||\'Other/Industrial\';if(!m[s])m[s]={sum:0,n:0};m[s].sum+=Number(x.from_open_pct||0);m[s].n++;});\n sectorPerf={};Object.entries(m).forEach(([s,v])=>sectorPerf[s]=v.n?v.sum/v.n:0);\n}\nfunction classify(x){\n const o=Number(x.open_0915||0),h=Number(x.day_high||0),l=Number(x.day_low||0),m=Number(x.from_open_pct||0);\n const s=x.sector||\'Other/Industrial\',sp=Number(sectorPerf[s]||0);\n const tol=Math.max(0.05,o*0.0005);\n const dLow=Math.abs(o-l),dHigh=Math.abs(h-o);\n const ol=dLow<=tol,oh=dHigh<=tol;\n let structure=ol?\'OPEN≈LOW\':oh?\'OPEN≈HIGH\':\'-\';\n let confirm=\'WATCH\',bias=\'NONE\';\n if(ol && m>=0.35 && sp>=0){confirm=\'CONFIRMED\';bias=\'CE\';}\n if(oh && m<=-0.35 && sp<=0){confirm=\'CONFIRMED\';bias=\'PE\';}\n return {...x,_structure:structure,_ol:ol,_oh:oh,_confirm:confirm,_bias:bias,_sectorPct:sp,\n   _dLowPct:o?dLow/o*100:0,_dHighPct:o?dHigh/o*100:0};\n}\nfunction setMode(m){mode=m;document.querySelectorAll(\'.toolbar button\').forEach(x=>x.classList.remove(\'activeBtn\'));document.getElementById(\'b\'+m).classList.add(\'activeBtn\');render();}\nfunction render(){\n buildSectorPerf();\n let a=data.map(classify),sec=sectorFilter.value;\n if(sec!==\'ALL\')a=a.filter(x=>(x.sector||\'Other/Industrial\')===sec);\n if(mode===\'OL\')a=a.filter(x=>x._ol);\n else if(mode===\'OH\')a=a.filter(x=>x._oh);\n else if(mode===\'OLC\')a=a.filter(x=>x._ol&&x._confirm===\'CONFIRMED\');\n else if(mode===\'OHC\')a=a.filter(x=>x._oh&&x._confirm===\'CONFIRMED\');\n\n a.sort((x,y)=>{\n   const xc=(x._confirm===\'CONFIRMED\'?1:0),yc=(y._confirm===\'CONFIRMED\'?1:0);\n   if(xc!==yc)return yc-xc;\n   return Math.abs(Number(y.from_open_pct||0))-Math.abs(Number(x.from_open_pct||0));\n });\n shown.textContent=\'Showing \'+a.length+\' of \'+data.length+\' stocks\';\n rows.innerHTML=a.map(x=>`<tr>\n  <td><b>${x.symbol}</b></td><td>${x.sector||\'Other/Industrial\'}</td>\n  <td>${x._structure===\'OPEN≈LOW\'?\'<span class="badge bull">OPEN≈LOW</span>\':x._structure===\'OPEN≈HIGH\'?\'<span class="badge bear">OPEN≈HIGH</span>\':\'-\'}</td>\n  <td class="right">${money(x.open_0915)}</td><td class="right ltp">${money(x.ltp)}</td>\n  <td class="right">${money(x.day_high)}</td><td class="right">${money(x.day_low)}</td>\n  <td class="right">${x._dLowPct.toFixed(3)}%</td><td class="right">${x._dHighPct.toFixed(3)}%</td>\n  <td class="right ${Number(x.from_open_pct)>=0?\'up\':\'down\'}">${pct(x.from_open_pct)}</td>\n  <td class="right ${x._sectorPct>=0?\'up\':\'down\'}">${pct(x._sectorPct)}</td>\n  <td>${x._confirm===\'CONFIRMED\'?\'<span class="badge \'+(x._bias===\'CE\'?\'bull\':\'bear\')+\'">CONFIRMED</span>\':\'<span class="badge watch">WATCH</span>\'}</td>\n  <td>${x._bias===\'CE\'?\'<span class="badge bull">CE</span>\':x._bias===\'PE\'?\'<span class="badge bear">PE</span>\':\'-\'}</td>\n </tr>`).join(\'\');\n\n const all=data.map(classify);\n cnt.textContent=data.length;ol.textContent=all.filter(x=>x._ol).length;oh.textContent=all.filter(x=>x._oh).length;\n olc.textContent=all.filter(x=>x._ol&&x._confirm===\'CONFIRMED\').length;ohc.textContent=all.filter(x=>x._oh&&x._confirm===\'CONFIRMED\').length;\n qp.textContent=all.filter(x=>x._bias===\'CE\').length+\' / \'+all.filter(x=>x._bias===\'PE\').length;\n}\nasync function load(){\n const r=await fetch(\'/api/fno-market-watch?ts=\'+Date.now());const d=await r.json();data=d.rows||[];\n updated.textContent=d.generated_at?\'Updated \'+String(d.generated_at).slice(11,19):\'Waiting...\';\n const old=sectorFilter.value;const secs=[...new Set(data.map(x=>x.sector||\'Other/Industrial\'))].sort();\n sectorFilter.innerHTML=\'<option value="ALL">All Sectors</option>\'+secs.map(s=>`<option value="${s}">${s}</option>`).join(\'\');\n if(old===\'ALL\'||secs.includes(old))sectorFilter.value=old;\n render();\n}\nload();setInterval(load,5000);\n</script></body></html>'

def snapshot():
    trades = _load_trades()
    today = datetime.now().date().isoformat()
    todays = [t for t in trades if str(t.get("entry_time") or "").startswith(today)]
    if todays:
        trades = todays

    open_trades = [t for t in trades if _status(t) == "OPEN"]
    closed = [t for t in trades if _status(t) == "CLOSED"]
    wins = [t for t in closed if _pnl(t) > 0 or str(t.get("result") or "").upper() == "WIN"]
    losses = [t for t in closed if _pnl(t) < 0 or str(t.get("result") or "").upper() == "LOSS"]

    rows = []
    for t in sorted(trades, key=lambda x: str(x.get("entry_time") or ""), reverse=True):
        rows.append({
            "id": str(t.get("paper_trade_id") or t.get("trade_id") or ""),
            "symbol": str(t.get("symbol") or "-"),
            "side": (str(t.get("direction") or "") + " " + str(t.get("option_type") or t.get("side") or "")).strip(),
            "strike": _num(t.get("strike")),
            "trade_date": str(t.get("entry_time") or "")[:10],
            "entry_time": _time(t.get("entry_time")),
            "exit_time": _time(t.get("exit_time")),
            "status": _status(t) or "-",
            "result": ("WIN" if (_pnl(t)>0 or str(t.get("result") or "").upper()=="WIN") else "LOSS" if (_pnl(t)<0 or str(t.get("result") or "").upper()=="LOSS") else "OPEN" if _status(t)=="OPEN" else "FLAT"),
            "entry": _num(t.get("entry_price")),
            "last": _num(t.get("last_option_price") or t.get("exit_price") or t.get("entry_price")),
            "pnl": _pnl(t),
            "return_pct": _return_pct(t),
            "capital": _capital(t),
            "mfe": _num(t.get("mfe_amount")),
            "mae": _num(t.get("mae_amount")),
            "exit_reason": str(t.get("exit_reason") or "-"),
            "setup": str(t.get("setup_family") or "-"),
            "quality": _num(t.get("momentum_score") or t.get("trade_quality_score")),
            "clean": _num(t.get("clean_trend_score")),
        })

    return {
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "trading_date": datetime.now().strftime("%d-%b-%Y"),
        "trading_day": datetime.now().strftime("%A"),
        "trade_count": len(trades),
        "open_count": len(open_trades),
        "closed_count": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / len(closed) * 100.0) if closed else 0.0, 2),
        "capital": round(sum(_capital(t) for t in trades), 2),
        "total_pnl": round(sum(_pnl(t) for t in trades), 2),
        "closed_pnl": round(sum(_pnl(t) for t in closed), 2),
        "open_pnl": round(sum(_pnl(t) for t in open_trades), 2),
        "rows": rows[:300],
    }

HTML = '''<!doctype html>
<html><head><meta charset="utf-8"><title>APlus Live Trading Terminal</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}
.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
.title{font-size:24px;font-weight:700}.brandrow{display:flex;align-items:center;gap:12px}.aplus-logo{width:48px;height:48px;flex:0 0 auto}.footer{margin-top:8px;padding:20px 24px;border-top:1px solid var(--line);display:flex;justify-content:center;align-items:center;gap:12px;position:relative;z-index:1;background:#0b1020}.footer .aplus-logo{width:38px;height:38px}.footer-title{font-size:17px;font-weight:700}.footer-sub{color:var(--muted);font-size:12px;margin-top:3px;text-align:center}.sub{color:var(--muted);font-size:13px;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;padding:18px 24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}
.label{color:var(--muted);font-size:12px}.value{font-size:24px;font-weight:750;margin-top:6px}.green{color:var(--green)}.red{color:var(--red)}
.tablewrap{padding:0 24px 24px}table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
th,td{padding:10px;border-bottom:1px solid var(--line);font-size:13px;text-align:left;white-space:nowrap}
th{color:var(--muted);font-weight:600;background:#0f1729;position:sticky;top:0}.right{text-align:right}
tr:hover{background:#18233b}.pill{padding:3px 8px;border-radius:999px;font-size:12px}.open{background:#1e3a5f}.closed{background:#243326}.loss{color:var(--red)}.win{color:var(--green)}
.watermark{position:fixed;left:50%;top:52%;transform:translate(-50%,-50%) rotate(-24deg);font-size:58px;font-weight:700;letter-spacing:2px;color:rgba(231,238,252,.085);white-space:nowrap;pointer-events:none;user-select:none;z-index:0}
.header,.grid,.tablewrap{position:relative;z-index:1}
.filterbar{padding:0 24px 14px;display:flex;gap:8px;align-items:center;position:relative;z-index:1}
.tradefilter{background:#121a2d;color:#e7eefc;border:1px solid #27334d;border-radius:9px;padding:8px 14px;cursor:pointer;font-weight:600}
.tradefilter.active{border-color:#17c964;background:#173527;color:#9ff0bd}
@media(max-width:1200px){.grid{grid-template-columns:repeat(3,1fr)}}
.exact-footer{padding:0!important;margin:12px 0 0!important;border-top:1px solid var(--line);background:#0b1020;display:block!important;width:100%;overflow:hidden}.exact-footer img{display:block;width:100%;height:auto;max-height:none;object-fit:contain}.crisp-footer{margin-top:14px;border-top:1px solid #1e6091;border-bottom:1px solid #1e6091;background:linear-gradient(90deg,#071426,#0b1b35,#071426);padding:16px 22px;display:grid;grid-template-columns:1.25fr 1.7fr 1.35fr .65fr;gap:22px;align-items:center;position:relative;z-index:2}.cf-quote{font-size:13px;line-height:1.45;color:#e7eefc}.cf-brand{display:flex;align-items:center;justify-content:center;gap:12px}.cf-logo{width:54px;height:54px}.cf-title{font-size:20px;font-weight:800;white-space:nowrap}.cf-title .live{color:#17c964}.cf-dev{font-size:12px;color:#d7e3f5;margin-top:4px;text-align:center}.cf-flow{font-size:11px;font-weight:700;white-space:nowrap}.cf-flow .dot{color:#17c964;padding:0 7px}.cf-safe{font-size:11px;color:#d7e3f5;margin-top:8px;white-space:nowrap}.cf-copy{text-align:right;font-size:11px;color:#d7e3f5;line-height:1.7}.cf-flag{font-size:18px}@media(max-width:1100px){.crisp-footer{grid-template-columns:1fr 1fr}.cf-copy{text-align:left}}</style></head><body><div id="aplus-main-nav" style="padding:12px 20px;display:flex;gap:10px;flex-wrap:wrap;border-bottom:1px solid #27334d;background:#0b1020">
<a href="/" style="padding:9px 14px;border:1px solid #22d3ee;border-radius:9px;color:#9ffcff;text-decoration:none;font-weight:800;background:#0f2730">LIVE TRADING</a>
<a href="/fno-market-watch" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">F&amp;O MARKET WATCH</a>
<a href="/sector-performance" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">SECTOR PERFORMANCE</a>
<a href="/opening-structure" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">OPENING STRUCTURE</a>
<a href="http://127.0.0.1:8766" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">TECHNICAL ALERTS</a><a href="/stock-charts" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">STOCK CHARTS</a>
</div>
<div class="watermark">Developed by Darpan Bobhate</div>
<div class="header"><div><div class="brandrow"><svg class="aplus-logo" viewBox="0 0 64 64" aria-label="APlus logo"><defs><linearGradient id="ag" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#22c55e"/></linearGradient></defs><path d="M8 54 L27 10 L43 54 H34 L27 34 L20 54 Z" fill="url(#ag)"/><path d="M18 47 L29 38 L37 42 L53 22" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><path d="M46 22 H54 V30" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round"/></svg><div><div class="title">APlus Live Trading Terminal</div><div class="sub">Developed by Darpan Bobhate</div><div class="sub">Auto-refreshes every 5 seconds from data/reports</div></div></div></div><div style="text-align:right"><div class="sub"><b><span id="trading_day">-</span>, <span id="trading_date">-</span></b></div><div class="sub">Last update: <span id="updated">-</span></div></div></div>
<div class="grid">
<div class="card"><div class="label">Total P&L</div><div id="total_pnl" class="value">-</div></div>
<div class="card"><div class="label">Open P&L</div><div id="open_pnl" class="value">-</div></div>
<div class="card"><div class="label">Closed P&L</div><div id="closed_pnl" class="value">-</div></div>
<div class="card"><div class="label">Trades</div><div id="trade_count" class="value">-</div></div>
<div class="card"><div class="label">Open / Closed</div><div id="open_closed" class="value">-</div></div>
<div class="card"><div class="label">Win Rate</div><div id="win_rate" class="value">-</div></div>
</div>
<div class="filterbar"><button class="tradefilter active" onclick="setFilter('ALL',this)">All Trades</button><button class="tradefilter" onclick="setFilter('OPEN',this)">Open</button><button class="tradefilter" onclick="setFilter('WIN',this)">Winners</button><button class="tradefilter" onclick="setFilter('LOSS',this)">Losers</button><span class="sub" id="shown_count"></span></div>
<div class="tablewrap"><table><thead><tr>
<th>Symbol</th><th>Side</th><th>Strike</th><th>Date</th><th>Entry</th><th>Exit</th><th>Status</th><th class="right">Entry ₹</th><th class="right">Last/Exit ₹</th><th class="right">P&L</th><th class="right">Return</th><th class="right">Capital</th><th>Setup</th><th>Exit Reason</th><th class="right">Q</th><th class="right">Clean</th>
</tr></thead><tbody id="rows"></tbody></table></div>
<script>
const fmt=n=>"₹"+Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:2});
const pct=n=>Number(n||0).toFixed(2)+"%";
const cls=n=>Number(n)>=0?"green":"red";
const prettyDate=x=>{if(!x)return "-";const p=x.split("-");if(p.length!==3)return x;const m=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];return p[2]+"-"+m[Number(p[1])-1]+"-"+p[0];};
let currentFilter="ALL",lastData=null;
function selectedRows(d){const rr=d.rows||[];return currentFilter==="ALL"?rr:rr.filter(x=>x.result===currentFilter);}
function setFilter(f,b){currentFilter=f;document.querySelectorAll(".tradefilter").forEach(x=>x.classList.remove("active"));b.classList.add("active");if(lastData){renderSummary(lastData);renderRows(lastData);}}
function renderSummary(d){
 const rr=selectedRows(d),closed=rr.filter(x=>x.status==="CLOSED"),open=rr.filter(x=>x.status==="OPEN"),wins=closed.filter(x=>x.result==="WIN");
 const total=rr.reduce((a,x)=>a+Number(x.pnl||0),0),cp=closed.reduce((a,x)=>a+Number(x.pnl||0),0),op=open.reduce((a,x)=>a+Number(x.pnl||0),0);
 const wr=closed.length?wins.length/closed.length*100:0;
 for(const [id,v] of [["total_pnl",total],["open_pnl",op],["closed_pnl",cp]]){const e=document.getElementById(id);e.textContent=fmt(v);e.className="value "+cls(v);}
 trade_count.textContent=rr.length;open_closed.textContent=open.length+" / "+closed.length;win_rate.textContent=pct(wr);
}
function renderRows(d){
 const rr=selectedRows(d);shown_count.textContent="Showing "+rr.length+" of "+(d.rows||[]).length+" trades";
 rows.innerHTML=rr.map(x=>{const pnlc=Number(x.pnl)>=0?"win":"loss",st=x.status==="OPEN"?"open":"closed";return `<tr><td><b>${x.symbol}</b></td><td>${x.side}</td><td>${x.strike}</td><td>${prettyDate(x.trade_date)}</td><td>${x.entry_time}</td><td>${x.exit_time}</td><td><span class="pill ${st}">${x.status}</span></td><td class="right">${fmt(x.entry)}</td><td class="right">${fmt(x.last)}</td><td class="right ${pnlc}"><b>${fmt(x.pnl)}</b></td><td class="right ${pnlc}">${pct(x.return_pct)}</td><td class="right">${fmt(x.capital)}</td><td>${x.setup}</td><td>${x.exit_reason}</td><td class="right">${Number(x.quality||0).toFixed(1)}</td><td class="right">${Number(x.clean||0).toFixed(1)}</td></tr>`}).join("");
}
async function load(){const r=await fetch('/api/snapshot?ts='+Date.now());const d=await r.json();lastData=d;updated.textContent=d.updated_at;trading_date.textContent=d.trading_date;trading_day.textContent=d.trading_day;renderSummary(d);renderRows(d);}
load();setInterval(load,5000);
</script><div class="crisp-footer"><div class="cf-quote">❝ &nbsp;<b>Discipline Creates Profits,</b><br>&nbsp;&nbsp;&nbsp;&nbsp;Automation Protects Them.</div><div class="cf-brand"><svg class="cf-logo" viewBox="0 0 64 64"><defs><linearGradient id="cfg" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#22c55e"/></linearGradient></defs><path d="M7 55 27 9l17 46h-10l-7-20-8 20z" fill="url(#cfg)"/><path d="m18 47 12-10 8 5 17-21" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><path d="M47 21h9v9" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round"/></svg><div><div class="cf-title">APlus <span class="live">Live</span> Trading Terminal</div><div class="cf-dev">— &nbsp; Developed by Darpan Bobhate &nbsp; —</div></div></div><div><div class="cf-flow">RESEARCH <span class="dot">•</span> ANALYZE <span class="dot">•</span> EXECUTE <span class="dot">•</span> IMPROVE</div><div class="cf-safe">🛡️ &nbsp; Paper Trading &nbsp; | &nbsp; NSE F&amp;O &nbsp; | &nbsp; No Live Orders</div></div><div class="cf-copy">© 2026 &nbsp; <span class="cf-flag">🇮🇳</span><br>All Rights Reserved</div></div></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/paper-history":
            body = history_html().encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/paper-days":
            body = json.dumps(days_payload()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/paper-history":
            q=parse_query(self.path); day=q.get("date") or ""
            body = json.dumps(history_payload(day)).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/fno-market-watch":
            body = json.dumps(_load_fno_market_watch()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/fno-market-watch":
            body = _mobileize_html(FNO_MARKET_WATCH_HTML).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/sector-performance":
            body = _mobileize_html(SECTOR_PERFORMANCE_HTML).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/opening-structure":
            body = _mobileize_html(OPENING_STRUCTURE_HTML).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/stock-charts":
            body=STOCK_CHART_HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/stock-chart-symbols":
            q=parse_query(self.path); day=q.get("day") or datetime.now().date().isoformat()
            body=json.dumps(symbols_payload(day)).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/stock-chart":
            q=parse_query(self.path); day=q.get("day") or datetime.now().date().isoformat(); symbol=q.get("symbol") or ""
            body=json.dumps(chart_payload(day,symbol)).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/snapshot":
            body = json.dumps(snapshot()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        body = _mobileize_html(HTML, self.headers.get("Host","127.0.0.1").split(":")[0]).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, fmt, *args):
        return

def main():
    print("="*72)
    print("APlus Live Trading Terminal")
    print("Open: http://127.0.0.1:8765")
    print("Press Ctrl+C to stop.")
    print("="*72)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
