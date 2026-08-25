from __future__ import annotations

from pathlib import Path
from datetime import datetime
import csv
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
HOST = "127.0.0.1"
PORT = 8765

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


FNO_MARKET_WATCH_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>APlus F&O Market Watch</title>
<style>:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}.title{font-size:24px;font-weight:750}.sub{color:var(--muted);font-size:12px;margin-top:4px}.toolbar{padding:14px 24px;display:flex;gap:8px;flex-wrap:wrap}.toolbar button,.toolbar select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 12px;font-weight:600}.toolbar button{cursor:pointer}.active{border-color:var(--green)!important;background:#173527!important;color:#9ff0bd!important}.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;padding:0 24px 14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.label{font-size:11px;color:var(--muted)}.value{font-size:20px;font-weight:750;margin-top:5px}.tablewrap{padding:0 24px 26px;overflow:auto}table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:9px 10px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}th{color:var(--muted);background:#0f1729;position:sticky;top:0}.right{text-align:right}.up{color:var(--green);font-weight:700}.down{color:var(--red);font-weight:700}a{color:#7dd3fc;text-decoration:none}.footer{padding:18px;text-align:center;color:var(--muted);border-top:1px solid var(--line)}@media(max-width:1100px){.cards{grid-template-columns:repeat(2,1fr)}}</style></head><body>
<div class="header"><div><div class="title">APlus F&O Market Watch</div><div class="sub">Full F&O universe • 09:15 Open → Now • Previous Close • High/Low • Gap • Sector</div></div><div style="text-align:right"><a href="/">← Live Trading Terminal</a><div id="updated" class="sub">Waiting for scanner data...</div></div></div>
<div class="cards"><div class="card"><div class="label">F&O Stocks</div><div class="value" id="count">-</div></div><div class="card"><div class="label">Advancing from Open</div><div class="value up" id="adv">-</div></div><div class="card"><div class="label">Declining from Open</div><div class="value down" id="dec">-</div></div><div class="card"><div class="label">Top From Open</div><div class="value up" id="topup">-</div></div><div class="card"><div class="label">Bottom From Open</div><div class="value down" id="topdown">-</div></div></div>
<div class="toolbar"><button id="bALL" class="active" onclick="setMode('ALL')">All</button><button id="bGAIN" onclick="setMode('GAIN')">Top Gainers</button><button id="bLOSS" onclick="setMode('LOSS')">Top Losers</button><button id="bUP" onclick="setMode('UP')">Strong Up ≥1%</button><button id="bDOWN" onclick="setMode('DOWN')">Strong Down ≤−1%</button><select id="sector" onchange="render()"><option value="ALL">All Sectors</option></select><select id="basis" onchange="render()"><option value="from_open_pct">Sort: From 09:15 Open %</option><option value="from_prev_close_pct">Sort: From Prev Close %</option><option value="gap_pct">Sort: Gap %</option></select><span class="sub" id="shown"></span></div>
<div class="tablewrap"><table><thead><tr><th>Symbol</th><th>Sector</th><th class="right">9:15 Open</th><th class="right">LTP</th><th class="right">Prev Close</th><th class="right">Gap %</th><th class="right">From Open %</th><th class="right">From Prev Close %</th><th class="right">Day High</th><th class="right">Day Low</th><th class="right">Range Pos %</th><th>Direction</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="footer">APlus Live Trading Terminal — Developed by Darpan Bobhate</div>
<script>let data=[],mode='ALL';const money=n=>'₹'+Number(n||0).toLocaleString('en-IN',{maximumFractionDigits:2});const pct=n=>(Number(n)>=0?'+':'')+Number(n||0).toFixed(2)+'%';function setMode(m){mode=m;document.querySelectorAll('.toolbar button').forEach(x=>x.classList.remove('active'));document.getElementById('b'+m).classList.add('active');render()}function render(){let a=[...data],sec=sector.value,b=basis.value;if(sec!=='ALL')a=a.filter(x=>x.sector===sec);if(mode==='GAIN')a=a.filter(x=>x[b]>0).sort((x,y)=>y[b]-x[b]).slice(0,30);else if(mode==='LOSS')a=a.filter(x=>x[b]<0).sort((x,y)=>x[b]-y[b]).slice(0,30);else if(mode==='UP')a=a.filter(x=>x.from_open_pct>=1).sort((x,y)=>y.from_open_pct-x.from_open_pct);else if(mode==='DOWN')a=a.filter(x=>x.from_open_pct<=-1).sort((x,y)=>x.from_open_pct-y.from_open_pct);else a.sort((x,y)=>y[b]-x[b]);shown.textContent='Showing '+a.length+' of '+data.length+' stocks';rows.innerHTML=a.map(x=>`<tr><td><b>${x.symbol}</b></td><td>${x.sector||'UNCLASSIFIED'}</td><td class="right">${money(x.open_0915)}</td><td class="right">${money(x.ltp)}</td><td class="right">${money(x.previous_close)}</td><td class="right ${x.gap_pct>=0?'up':'down'}">${pct(x.gap_pct)}</td><td class="right ${x.from_open_pct>=0?'up':'down'}">${pct(x.from_open_pct)}</td><td class="right ${x.from_prev_close_pct>=0?'up':'down'}">${pct(x.from_prev_close_pct)}</td><td class="right">${money(x.day_high)}</td><td class="right">${money(x.day_low)}</td><td class="right">${Number(x.range_position_pct||0).toFixed(1)}</td><td class="${x.direction==='UP'?'up':x.direction==='DOWN'?'down':''}">${x.direction==='UP'?'▲':x.direction==='DOWN'?'▼':'•'} ${x.direction}</td></tr>`).join('')}async function load(){const r=await fetch('/api/fno-market-watch?ts='+Date.now());const d=await r.json();data=d.rows||[];count.textContent=data.length;adv.textContent=data.filter(x=>x.from_open_pct>0).length;dec.textContent=data.filter(x=>x.from_open_pct<0).length;if(data.length){let u=[...data].sort((a,b)=>b.from_open_pct-a.from_open_pct)[0],dn=[...data].sort((a,b)=>a.from_open_pct-b.from_open_pct)[0];topup.textContent=u.symbol+' '+pct(u.from_open_pct);topdown.textContent=dn.symbol+' '+pct(dn.from_open_pct)}updated.textContent=d.generated_at?'Updated '+String(d.generated_at).slice(11,19):'Waiting for scanner data...';const old=sector.value;const secs=[...new Set(data.map(x=>x.sector||'UNCLASSIFIED'))].sort();sector.innerHTML='<option value="ALL">All Sectors</option>'+secs.map(x=>`<option value="${x}">${x}</option>`).join('');if(old==='ALL'||secs.includes(old))sector.value=old;render()}load();setInterval(load,5000)</script><a href="/fno-market-watch" style="position:fixed;right:22px;bottom:22px;z-index:999;background:#17c964;color:#04130a;text-decoration:none;font-weight:800;padding:11px 16px;border-radius:12px;box-shadow:0 5px 24px #0008">F&amp;O MARKET WATCH</a></body></html>"""

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
.exact-footer{padding:0!important;margin:12px 0 0!important;border-top:1px solid var(--line);background:#0b1020;display:block!important;width:100%;overflow:hidden}.exact-footer img{display:block;width:100%;height:auto;max-height:none;object-fit:contain}.crisp-footer{margin-top:14px;border-top:1px solid #1e6091;border-bottom:1px solid #1e6091;background:linear-gradient(90deg,#071426,#0b1b35,#071426);padding:16px 22px;display:grid;grid-template-columns:1.25fr 1.7fr 1.35fr .65fr;gap:22px;align-items:center;position:relative;z-index:2}.cf-quote{font-size:13px;line-height:1.45;color:#e7eefc}.cf-brand{display:flex;align-items:center;justify-content:center;gap:12px}.cf-logo{width:54px;height:54px}.cf-title{font-size:20px;font-weight:800;white-space:nowrap}.cf-title .live{color:#17c964}.cf-dev{font-size:12px;color:#d7e3f5;margin-top:4px;text-align:center}.cf-flow{font-size:11px;font-weight:700;white-space:nowrap}.cf-flow .dot{color:#17c964;padding:0 7px}.cf-safe{font-size:11px;color:#d7e3f5;margin-top:8px;white-space:nowrap}.cf-copy{text-align:right;font-size:11px;color:#d7e3f5;line-height:1.7}.cf-flag{font-size:18px}@media(max-width:1100px){.crisp-footer{grid-template-columns:1fr 1fr}.cf-copy{text-align:left}}</style></head><body>
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
        if path == "/api/fno-market-watch":
            body = json.dumps(_load_fno_market_watch()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/fno-market-watch":
            body = FNO_MARKET_WATCH_HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/snapshot":
            body = json.dumps(snapshot()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        body = HTML.encode("utf-8")
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
