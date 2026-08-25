from pathlib import Path
from datetime import datetime
import shutil, py_compile

p=Path("aplus_live_pnl_dashboard.py")
if not p.is_file(): raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
b=Path(f"aplus_live_pnl_dashboard_before_filters_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p,b)
s=p.read_text(encoding="utf-8")

a='"status": _status(t) or "-",\n            "entry":'
r='"status": _status(t) or "-",\n            "result": ("WIN" if _status(t)=="CLOSED" and _pnl(t)>0 else "LOSS" if _status(t)=="CLOSED" and _pnl(t)<0 else "OPEN" if _status(t)=="OPEN" else "FLAT"),\n            "entry":'
if a not in s: raise SystemExit("FAIL: row anchor not found")
s=s.replace(a,r,1)

a='<div class="tablewrap"><table>'
r="""<div style="padding:0 24px 14px;display:flex;gap:8px">
<button onclick="setFilter('ALL',this)">All Trades</button>
<button onclick="setFilter('OPEN',this)">Open</button>
<button onclick="setFilter('WIN',this)">Winners</button>
<button onclick="setFilter('LOSS',this)">Losers</button>
<span class="sub" id="shown_count"></span></div>
<div class="tablewrap"><table>"""
if a not in s: raise SystemExit("FAIL: table anchor not found")
s=s.replace(a,r,1)

a='async function load(){'
r='let currentFilter="ALL"; function setFilter(f,b){currentFilter=f;document.querySelectorAll("button").forEach(x=>x.style.borderColor="");b.style.borderColor="#17c964";if(window.lastData)renderRows(window.lastData)} function renderRows(d){let rr=currentFilter==="ALL"?d.rows:d.rows.filter(x=>x.result===currentFilter);document.getElementById("shown_count").textContent="Showing "+rr.length+" of "+d.rows.length+" trades";rows.innerHTML=rr.map(x=>{const pnlc=Number(x.pnl)>=0?"win":"loss";const st=x.status=="OPEN"?"open":"closed";return `<tr><td><b>${x.symbol}</b></td><td>${x.side}</td><td>${x.strike}</td><td>${x.entry_time}</td><td>${x.exit_time}</td><td><span class="pill ${st}">${x.status}</span></td><td class="right">${fmt(x.entry)}</td><td class="right">${fmt(x.last)}</td><td class="right ${pnlc}"><b>${fmt(x.pnl)}</b></td><td class="right ${pnlc}">${pct(x.return_pct)}</td><td class="right">${fmt(x.capital)}</td><td>${x.setup}</td><td>${x.exit_reason}</td><td class="right">${Number(x.quality||0).toFixed(1)}</td><td class="right">${Number(x.clean||0).toFixed(1)}</td></tr>`}).join("")} async function load(){'
if a not in s: raise SystemExit("FAIL: JS anchor not found")
s=s.replace(a,r,1)

old='rows.innerHTML=d.rows.map(x=>{'
if old not in s: raise SystemExit("FAIL: render anchor not found")
start=s.index(old)
end=s.index('}load(); setInterval(load,5000);',start)
prefix=s[:start]
suffix=s[end:]
s=prefix+'window.lastData=d; renderRows(d);\n'+suffix

p.write_text(s,encoding="utf-8")
try: py_compile.compile(str(p),doraise=True)
except Exception:
    shutil.copy2(b,p); raise
print("SUCCESS: All/Open/Winners/Losers one-click filters installed")
print("Backup:",b)
