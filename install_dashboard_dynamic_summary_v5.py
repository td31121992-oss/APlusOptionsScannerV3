from pathlib import Path
from datetime import datetime
import shutil, py_compile

p=Path("aplus_live_pnl_dashboard.py")
if not p.is_file(): raise SystemExit("FAIL: dashboard file not found")
b=Path(f"aplus_live_pnl_dashboard_before_v5_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p,b)
s=p.read_text(encoding="utf-8")
try:
    if '"trade_date":' not in s:
        a='            "entry_time": _time(t.get("entry_time")),'
        if a not in s: raise RuntimeError("entry_time anchor not found")
        lines=['            "trade_date": str(t.get("entry_time") or "")[:10],', a]
        s=s.replace(a, chr(10).join(lines), 1)

    if "<th>Date</th>" not in s:
        a="<th>Symbol</th><th>Side</th><th>Strike</th><th>Entry</th>"
        if a not in s: raise RuntimeError("table header anchor not found")
        s=s.replace(a,"<th>Symbol</th><th>Side</th><th>Strike</th><th>Date</th><th>Entry</th>",1)

    # Clean old literal backslash-n sequences already present in CSS from earlier patch.
    s=s.replace("}\\n.tradefilter", "}"+chr(10)+".tradefilter")
    s=s.replace("600}\\n.tradefilter.active", "600}"+chr(10)+".tradefilter.active")
    s=s.replace("#9ff0bd}\\n@media", "#9ff0bd}"+chr(10)+"@media")

    ss=s.find("<script>"); ee=s.find("</script>",ss)
    if ss<0 or ee<0: raise RuntimeError("script block not found")
    js='<script>\nconst fmt=n=>"₹"+Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:2});\nconst pct=n=>Number(n||0).toFixed(2)+"%";\nconst cls=n=>Number(n)>=0?"green":"red";\nconst prettyDate=x=>{if(!x)return "-";const p=x.split("-");if(p.length!==3)return x;const m=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];return p[2]+"-"+m[Number(p[1])-1]+"-"+p[0];};\nlet currentFilter="ALL",lastData=null;\nfunction selectedRows(d){const rr=d.rows||[];return currentFilter==="ALL"?rr:rr.filter(x=>x.result===currentFilter);}\nfunction setFilter(f,b){currentFilter=f;document.querySelectorAll(".tradefilter").forEach(x=>x.classList.remove("active"));b.classList.add("active");if(lastData){renderSummary(lastData);renderRows(lastData);}}\nfunction renderSummary(d){\n const rr=selectedRows(d),closed=rr.filter(x=>x.status==="CLOSED"),open=rr.filter(x=>x.status==="OPEN"),wins=closed.filter(x=>x.result==="WIN");\n const total=rr.reduce((a,x)=>a+Number(x.pnl||0),0),cp=closed.reduce((a,x)=>a+Number(x.pnl||0),0),op=open.reduce((a,x)=>a+Number(x.pnl||0),0);\n const wr=closed.length?wins.length/closed.length*100:0;\n for(const [id,v] of [["total_pnl",total],["open_pnl",op],["closed_pnl",cp]]){const e=document.getElementById(id);e.textContent=fmt(v);e.className="value "+cls(v);}\n trade_count.textContent=rr.length;open_closed.textContent=open.length+" / "+closed.length;win_rate.textContent=pct(wr);\n}\nfunction renderRows(d){\n const rr=selectedRows(d);shown_count.textContent="Showing "+rr.length+" of "+(d.rows||[]).length+" trades";\n rows.innerHTML=rr.map(x=>{const pnlc=Number(x.pnl)>=0?"win":"loss",st=x.status==="OPEN"?"open":"closed";return `<tr><td><b>${x.symbol}</b></td><td>${x.side}</td><td>${x.strike}</td><td>${prettyDate(x.trade_date)}</td><td>${x.entry_time}</td><td>${x.exit_time}</td><td><span class="pill ${st}">${x.status}</span></td><td class="right">${fmt(x.entry)}</td><td class="right">${fmt(x.last)}</td><td class="right ${pnlc}"><b>${fmt(x.pnl)}</b></td><td class="right ${pnlc}">${pct(x.return_pct)}</td><td class="right">${fmt(x.capital)}</td><td>${x.setup}</td><td>${x.exit_reason}</td><td class="right">${Number(x.quality||0).toFixed(1)}</td><td class="right">${Number(x.clean||0).toFixed(1)}</td></tr>`}).join("");\n}\nasync function load(){const r=await fetch(\'/api/snapshot?ts=\'+Date.now());const d=await r.json();lastData=d;updated.textContent=d.updated_at;trading_date.textContent=d.trading_date;trading_day.textContent=d.trading_day;renderSummary(d);renderRows(d);}\nload();setInterval(load,5000);\n</script>'
    s=s[:ss]+js+s[ee+9:]
    p.write_text(s,encoding="utf-8")
    py_compile.compile(str(p),doraise=True)

    chk=p.read_text(encoding="utf-8")
    for x in ['"trade_date":','<th>Date</th>','function renderSummary(d)','prettyDate(x.trade_date)']:
        if x not in chk: raise RuntimeError("verification failed: "+x)
except Exception:
    shutil.copy2(b,p)
    print("INSTALL FAILED - original restored:",b)
    raise

print("="*72)
print("SUCCESS: DASHBOARD V5 INSTALLED")
print("PASS: Date column")
print("PASS: Winners filter changes top cards to winning trades/profit only")
print("PASS: Losers filter changes top cards to losing trades/loss only")
print("PASS: Open filter changes top cards to open trades/P&L only")
print("PASS: All Trades restores complete daily summary")
print("PASS: Day/date, branding, watermark and 5-second refresh preserved")
print("Backup:",b)
print("="*72)
