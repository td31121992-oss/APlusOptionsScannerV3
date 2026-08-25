from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from paper_trade_history_store import load_history

ROOT=Path(__file__).resolve().parent
REPORTS=ROOT/"data"/"reports"

def _num(v,d=0.0):
    try:return float(v) if v not in ("",None) else d
    except Exception:return d
def _status(t):return str(t.get("status") or "").upper()
def _pnl(t):return _num(t.get("net_pnl") if t.get("net_pnl") not in ("",None) else t.get("pnl"))
def _capital(t):return _num(t.get("capital_deployed") or t.get("capital"))
def _date(t):
    s=str(t.get("entry_time") or t.get("generated_at") or "")
    return s[:10] if len(s)>=10 else ""
def _time(v):
    s=str(v or "")
    if "T" in s:return s.split("T",1)[1].split("+",1)[0].split(".",1)[0]
    return s or "-"

def all_trades():
    rows=load_history(REPORTS)
    p=REPORTS/"paper_trades_latest.json"
    if p.exists():
        try:
            obj=json.loads(p.read_text(encoding="utf-8"));latest=obj.get("paper_trades") or obj.get("trades") or []
            by={str(x.get("paper_trade_id") or ""):dict(x) for x in rows if str(x.get("paper_trade_id") or "")}
            loose=[dict(x) for x in rows if not str(x.get("paper_trade_id") or "")]
            for x in latest:
                if not isinstance(x,dict):continue
                k=str(x.get("paper_trade_id") or "")
                if k:by[k]=dict(x)
                else:loose.append(dict(x))
            rows=list(by.values())+loose
        except Exception:pass
    return sorted(rows,key=lambda x:str(x.get("entry_time") or x.get("generated_at") or ""))

def days_payload():
    rows=all_trades();dates=sorted({d for d in (_date(x) for x in rows) if d},reverse=True);summaries=[]
    for d in dates:
        rr=[x for x in rows if _date(x)==d];closed=[x for x in rr if _status(x)=="CLOSED"];wins=[x for x in closed if _pnl(x)>0 or str(x.get("result") or "").upper()=="WIN"]
        cap=sum(_capital(x) for x in rr);pnl=sum(_pnl(x) for x in rr)
        summaries.append({"date":d,"trades":len(rr),"wins":len(wins),"losses":len(closed)-len(wins),"win_rate":round(len(wins)/len(closed)*100,2) if closed else 0.0,"capital":round(cap,2),"net_pnl":round(pnl,2),"return_pct":round(pnl/cap*100,4) if cap else 0.0})
    return {"dates":dates,"summaries":summaries}

def history_payload(day=""):
    rows=all_trades();day=day or datetime.now().date().isoformat();rr=[x for x in rows if _date(x)==day]
    closed=[x for x in rr if _status(x)=="CLOSED"];wins=[x for x in closed if _pnl(x)>0 or str(x.get("result") or "").upper()=="WIN"]
    cap=sum(_capital(x) for x in rr);pnl=sum(_pnl(x) for x in rr);out=[]
    for t in sorted(rr,key=lambda x:str(x.get("entry_time") or ""),reverse=True):
        out.append({"symbol":str(t.get("symbol") or "-"),"direction":str(t.get("direction") or ""),"option_type":str(t.get("option_type") or t.get("side") or ""),"strike":_num(t.get("strike")),"expiry":str(t.get("expiry") or "-"),"entry_time":_time(t.get("entry_time")),"exit_time":_time(t.get("exit_time")),"status":_status(t) or "-","entry":_num(t.get("entry_price")),"exit":_num(t.get("exit_price") or t.get("last_option_price")),"qty":int(_num(t.get("quantity"))),"capital":_capital(t),"risk_amount":_num(t.get("planned_risk_amount") or t.get("total_risk")),"risk_pct":_num(t.get("planned_risk_percent")),"pnl":_pnl(t),"return_pct":_num(t.get("return_percent")),"mfe":_num(t.get("mfe_amount")),"mae":_num(t.get("mae_amount")),"entry_reason":str(t.get("entry_reason") or "-"),"exit_reason":str(t.get("exit_reason") or "-"),"setup":str(t.get("setup_family") or "-"),"result":str(t.get("result") or "-")})
    return {"date":day,"trade_count":len(rr),"open":len(rr)-len(closed),"closed":len(closed),"wins":len(wins),"losses":len(closed)-len(wins),"win_rate":round(len(wins)/len(closed)*100,2) if closed else 0.0,"capital":round(cap,2),"net_pnl":round(pnl,2),"return_pct":round(pnl/cap*100,4) if cap else 0.0,"rows":out}

def history_html():
    return """<!doctype html><html><head><meta charset='utf-8'><title>APlus Paper Trade History</title>
<style>:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}.title{font-size:24px;font-weight:700}.sub{color:var(--muted);font-size:13px}.nav a{color:var(--text);margin-left:16px}.controls{padding:16px 24px}.controls select{background:var(--panel);color:var(--text);border:1px solid var(--line);padding:8px}.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;padding:0 24px 18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}.label{color:var(--muted);font-size:12px}.value{font-size:22px;font-weight:750}.win{color:var(--green)}.loss{color:var(--red)}.tablewrap,.summary{padding:0 24px 24px;overflow:auto}table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:9px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap;text-align:left}th{color:var(--muted);background:#0f1729}.right{text-align:right}.reason{max-width:320px;overflow:hidden;text-overflow:ellipsis}@media(max-width:1200px){.grid{grid-template-columns:repeat(3,1fr)}}</style></head>
<body><div class='header'><div><div class='title'>APlus Paper Trade History</div><div class='sub'>Permanent read-only journal by trading day</div></div><div class='nav'><a href='/'>LIVE</a><a href='/stock-charts'>STOCK CHARTS</a></div></div>
<div class='controls'>Trading date: <select id='day'></select></div>
<div class='grid'><div class='card'><div class='label'>Trades</div><div id='trades' class='value'>-</div></div><div class='card'><div class='label'>Open / Closed</div><div id='oc' class='value'>-</div></div><div class='card'><div class='label'>Wins / Losses</div><div id='wl' class='value'>-</div></div><div class='card'><div class='label'>Win Rate</div><div id='wr' class='value'>-</div></div><div class='card'><div class='label'>Capital</div><div id='capital' class='value'>-</div></div><div class='card'><div class='label'>Net P&L</div><div id='pnl' class='value'>-</div></div></div>
<div class='tablewrap'><table><thead><tr><th>Symbol</th><th>Side</th><th>Strike</th><th>Expiry</th><th>Entry</th><th>Exit</th><th>Status</th><th>Entry ₹</th><th>Exit/Last ₹</th><th>Qty</th><th>Capital</th><th>Risk ₹</th><th>Risk %</th><th>P&L</th><th>Return</th><th>MFE ₹</th><th>MAE ₹</th><th>Result</th><th>Setup</th><th>Entry Reason</th><th>Exit Reason</th></tr></thead><tbody id='rows'></tbody></table></div>
<div class='summary'><h3>Daily Summary</h3><table><thead><tr><th>Date</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>Capital</th><th>Net P&L</th><th>Return</th></tr></thead><tbody id='days'></tbody></table></div>
<script>const money=n=>'₹'+Number(n||0).toLocaleString('en-IN',{maximumFractionDigits:2}),pct=n=>Number(n||0).toFixed(2)+'%',cls=n=>Number(n)>=0?'win':'loss';
async function loadDays(){const d=await (await fetch('/api/paper-days?ts='+Date.now())).json(),sel=document.getElementById('day'),old=sel.value;sel.innerHTML=d.dates.map(x=>`<option>${x}</option>`).join('');if(old&&d.dates.includes(old))sel.value=old;days.innerHTML=d.summaries.map(x=>`<tr><td>${x.date}</td><td>${x.trades}</td><td>${x.wins}</td><td>${x.losses}</td><td>${pct(x.win_rate)}</td><td>${money(x.capital)}</td><td class='${cls(x.net_pnl)}'>${money(x.net_pnl)}</td><td>${pct(x.return_pct)}</td></tr>`).join('');}
async function load(){const d=await (await fetch('/api/paper-history?date='+encodeURIComponent(day.value||'')+'&ts='+Date.now())).json();trades.textContent=d.trade_count;oc.textContent=d.open+' / '+d.closed;wl.textContent=d.wins+' / '+d.losses;wr.textContent=pct(d.win_rate);capital.textContent=money(d.capital);pnl.textContent=money(d.net_pnl);pnl.className='value '+cls(d.net_pnl);rows.innerHTML=d.rows.map(x=>`<tr><td><b>${x.symbol}</b></td><td>${x.direction} ${x.option_type}</td><td>${x.strike}</td><td>${x.expiry}</td><td>${x.entry_time}</td><td>${x.exit_time}</td><td>${x.status}</td><td>${money(x.entry)}</td><td>${money(x.exit)}</td><td>${x.qty}</td><td>${money(x.capital)}</td><td>${money(x.risk_amount)}</td><td>${pct(x.risk_pct)}</td><td class='${cls(x.pnl)}'>${money(x.pnl)}</td><td>${pct(x.return_pct)}</td><td>${money(x.mfe)}</td><td>${money(x.mae)}</td><td>${x.result}</td><td>${x.setup}</td><td class='reason'>${x.entry_reason}</td><td class='reason'>${x.exit_reason}</td></tr>`).join('');}
day.addEventListener('change',load);(async()=>{await loadDays();await load()})();setInterval(async()=>{await loadDays();await load()},10000);</script></body></html>"""
