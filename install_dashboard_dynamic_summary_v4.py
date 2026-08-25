from pathlib import Path
from datetime import datetime
import shutil, py_compile
p=Path("aplus_live_pnl_dashboard.py")
if not p.is_file(): raise SystemExit("FAIL: dashboard file not found")
b=Path(f"aplus_live_pnl_dashboard_before_dynamic_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p,b)
s=p.read_text(encoding="utf-8")
try:
    if '"trade_date":' not in s:
        a='            "entry_time": _time(t.get("entry_time")),'; r='            "trade_date": str(t.get("entry_time") or "")[:10],\\n'+a
        if a not in s: raise RuntimeError("entry anchor not found")
        s=s.replace(a,r,1)
    if "<th>Date</th>" not in s:
        a="<th>Entry</th>"
        if a not in s: raise RuntimeError("header anchor not found")
        s=s.replace(a,"<th>Date</th>"+a,1)
    ss=s.find("<script>"); ee=s.find("</script>",ss)
    if ss<0 or ee<0: raise RuntimeError("script not found")
    js='<script>\nconst fmt=n=>"₹"+Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:2});\nconst pct=n=>Number(n||0).toFixed(2)+"%"; const cls=n=>Number(n)>=0?"green":"red";\nconst prettyDate=x=>{if(!x)return "-";const p=x.split("-");if(p.length!==3)return x;const m=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];return p[2]+"-"+m[Number(p[1])-1]+"-"+p[0];};\nlet currentFilter="ALL",lastData=null;\nfunction selectedRows(d){let rr=d.rows||[];return currentFilter==="ALL"?rr:rr.filter(x=>x.result===currentFilter);}\nfunction setFilter(f,b){currentFilter=f;document.querySelectorAll(".tradefilter").forEach(x=>x.classList.remove("active"));b.classList.add("active");if(lastData){renderSummary(lastData);renderRows(lastData);}}\nfunction renderSummary(d){const rr=selectedRows(d),closed=rr.filter(x=>x.status==="CLOSED"),open=rr.filter(x=>x.status==="OPEN"),wins=closed.filter(x=>Number(x.pnl)>0);const pnl=rr.reduce((a,x)=>a+Number(x.pnl||0),0),cp=closed.reduce((a,x)=>a+Number(x.pnl||0),0),op=open.reduce((a,x)=>a+Number(x.pnl||0),0),wr=closed.length?wins.length/closed.length*100:0;for(const [id,v] of [["total_pnl",pnl],["open_pnl",op],["closed_pnl",cp]]){let e=document.getElementById(id);e.textContent=fmt(v);e.className="value "+cls(v);}trade_count.textContent=rr.length;open_closed.textContent=open.length+" / "+closed.length;win_rate.textContent=pct(wr);}\nfunction renderRows(d){const rr=selectedRows(d);document.getElementById("shown_count").textContent="Showing "+rr.length+" of "+(d.rows||[]).length+" trades";rows.innerHTML=rr.map(x=>{const pnlc=Number(x.pnl)>=0?"win":"loss",st=x.status==="OPEN"?"open":"closed";return `<tr><td><b>${x.symbol}</b></td><td>${x.side}</td><td>${x.strike}</td><td>${prettyDate(x.trade_date)}</td><td>${x.entry_time}</td><td>${x.exit_time}</td><td><span class="pill ${st}">${x.status}</span></td><td class="right">${fmt(x.entry)}</td><td class="right">${fmt(x.last)}</td><td class="right ${pnlc}"><b>${fmt(x.pnl)}</b></td><td class="right ${pnlc}">${pct(x.return_pct)}</td><td class="right">${fmt(x.capital)}</td><td>${x.setup}</td><td>${x.exit_reason}</td><td class="right">${Number(x.quality||0).toFixed(1)}</td><td class="right">${Number(x.clean||0).toFixed(1)}</td></tr>`}).join("");}\nasync function load(){const r=await fetch(\'/api/snapshot?ts=\'+Date.now());const d=await r.json();lastData=d;updated.textContent=d.updated_at;if(document.getElementById("trading_date"))trading_date.textContent=d.trading_date;if(document.getElementById("trading_day"))trading_day.textContent=d.trading_day;renderSummary(d);renderRows(d);}\nload();setInterval(load,5000);\n</script>'
    s=s[:ss]+js+s[ee+9:]
    p.write_text(s,encoding="utf-8")
    py_compile.compile(str(p),doraise=True)
except Exception:
    shutil.copy2(b,p)
    print("INSTALL FAILED - original restored:",b)
    raise
print("SUCCESS: Date column + filter-aware top summary installed")
print("Winners/Losers/Open/All Trades now update both table and cards")
print("Backup:",b)
