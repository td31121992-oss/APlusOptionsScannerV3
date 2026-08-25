from pathlib import Path
from datetime import datetime
import shutil, py_compile
p=Path("aplus_live_pnl_dashboard.py")
if not p.is_file(): raise SystemExit("FAIL: dashboard file not found")
backup=Path(f"aplus_live_pnl_dashboard_before_combined_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p,backup)
s=p.read_text(encoding="utf-8")
try:
    s=s.replace("APlus PAPER Live P&L Dashboard","APlus Live Trading Terminal")
    if '"result":' not in s:
        a='            "status": _status(t) or "-",\\n'
        r=a+'            "result": ("WIN" if _status(t)=="CLOSED" and _pnl(t)>0 else "LOSS" if _status(t)=="CLOSED" and _pnl(t)<0 else "OPEN" if _status(t)=="OPEN" else "FLAT"),\\n'
        if a not in s: raise RuntimeError("status anchor not found")
        s=s.replace(a,r,1)
    css=".watermark{position:fixed;left:50%;top:52%;transform:translate(-50%,-50%) rotate(-24deg);font-size:52px;font-weight:700;color:rgba(231,238,252,.045);pointer-events:none;z-index:0}\\n.header,.grid,.filterbar,.tablewrap{position:relative;z-index:1}\\n.filterbar{padding:0 24px 14px;display:flex;gap:8px;align-items:center}\\n.tradefilter{background:#121a2d;color:#e7eefc;border:1px solid #27334d;border-radius:9px;padding:8px 14px;cursor:pointer;font-weight:600}\\n.tradefilter.active{border-color:#17c964;background:#173527;color:#9ff0bd}\\n"
    if ".watermark{" not in s: s=s.replace("</style>",css+"</style>",1)
    wm='<div class="watermark">Developed by Darpan Bobhate</div>'
    if wm not in s: s=s.replace("<body>","<body>\\n"+wm,1)
    if 'class="filterbar"' not in s:
        a='<div class="tablewrap"><table>'
        c='<div class="filterbar"><button class="tradefilter active" onclick="setFilter(\\\'ALL\\\',this)">All Trades</button><button class="tradefilter" onclick="setFilter(\\\'OPEN\\\',this)">Open</button><button class="tradefilter" onclick="setFilter(\\\'WIN\\\',this)">Winners</button><button class="tradefilter" onclick="setFilter(\\\'LOSS\\\',this)">Losers</button><span class="sub" id="shown_count"></span></div>\\n'
        if a not in s: raise RuntimeError("table anchor not found")
        s=s.replace(a,c+a,1)
    ss=s.find("<script>"); ee=s.find("</script>",ss)
    if ss<0 or ee<0: raise RuntimeError("script block not found")
    js="""<script>
const fmt=n=>"₹"+Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:2});
const pct=n=>Number(n||0).toFixed(2)+"%"; const cls=n=>Number(n)>=0?"green":"red";
let currentFilter="ALL",lastData=null;
function setFilter(f,b){currentFilter=f;document.querySelectorAll(".tradefilter").forEach(x=>x.classList.remove("active"));b.classList.add("active");if(lastData)renderRows(lastData);}
function renderRows(d){let rr=d.rows||[];if(currentFilter!=="ALL")rr=rr.filter(x=>x.result===currentFilter);document.getElementById("shown_count").textContent="Showing "+rr.length+" of "+(d.rows||[]).length+" trades";rows.innerHTML=rr.map(x=>{const pnlc=Number(x.pnl)>=0?"win":"loss";const st=x.status=="OPEN"?"open":"closed";return `<tr><td><b>${x.symbol}</b></td><td>${x.side}</td><td>${x.strike}</td><td>${x.entry_time}</td><td>${x.exit_time}</td><td><span class="pill ${st}">${x.status}</span></td><td class="right">${fmt(x.entry)}</td><td class="right">${fmt(x.last)}</td><td class="right ${pnlc}"><b>${fmt(x.pnl)}</b></td><td class="right ${pnlc}">${pct(x.return_pct)}</td><td class="right">${fmt(x.capital)}</td><td>${x.setup}</td><td>${x.exit_reason}</td><td class="right">${Number(x.quality||0).toFixed(1)}</td><td class="right">${Number(x.clean||0).toFixed(1)}</td></tr>`}).join("");}
async function load(){const r=await fetch('/api/snapshot?ts='+Date.now());const d=await r.json();lastData=d;updated.textContent=d.updated_at;for(const k of ["total_pnl","open_pnl","closed_pnl"]){let e=document.getElementById(k);e.textContent=fmt(d[k]);e.className="value "+cls(d[k]);}trade_count.textContent=d.trade_count;open_closed.textContent=d.open_count+" / "+d.closed_count;win_rate.textContent=pct(d.win_rate);renderRows(d);}
load();setInterval(load,5000);
</script>"""
    s=s[:ss]+js+s[ee+9:]
    p.write_text(s,encoding="utf-8")
    py_compile.compile(str(p),doraise=True)
except Exception:
    shutil.copy2(backup,p)
    print("INSTALL FAILED - original restored:",backup)
    raise
print("SUCCESS: Combined dashboard UI installed")
print("Title: APlus Live Trading Terminal")
print("Watermark: Developed by Darpan Bobhate")
print("Filters: All Trades | Open | Winners | Losers")
print("Backup:",backup)
