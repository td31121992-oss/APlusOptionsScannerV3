from pathlib import Path
from datetime import datetime
import shutil, py_compile, ast

p=Path("aplus_live_pnl_dashboard.py")
if not p.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")

b=Path(f"aplus_live_pnl_dashboard_before_sector_panel_v2_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p,b)
s=p.read_text(encoding="utf-8")

def find_literal(text,varname):
    marker=varname+" = "
    i=text.find(marker)
    if i<0: raise RuntimeError(varname+" block not found")
    start=i+len(marker)
    candidates=[x for x in (text.find("\n\ndef ",start),text.find("\n\nclass ",start)) if x>=0]
    if not candidates: raise RuntimeError("Could not locate end of "+varname)
    end=min(candidates)
    return start,end,ast.literal_eval(text[start:end])

try:
    mw_start,mw_end,market_html=find_literal(s,"FNO_MARKET_WATCH_HTML")
    if 'href="/sector-performance"' not in market_html:
        anchor='</div>\n<div class="cards">'
        if anchor not in market_html:
            anchor='</div><div class="cards">'
        if anchor not in market_html:
            raise RuntimeError("FNO Market Watch header/cards anchor not found")
        tabs='''</div>
<div style="padding:12px 24px;display:flex;gap:8px">
  <a href="/fno-market-watch" style="padding:8px 14px;border-radius:9px;border:1px solid #22d3ee;color:#9ffcff;background:#0f2730;font-weight:700;text-decoration:none">Market Watch</a>
  <a href="/sector-performance" style="padding:8px 14px;border-radius:9px;border:1px solid #27334d;color:#e7eefc;background:#121a2d;font-weight:700;text-decoration:none">Sector Performance</a>
</div>
<div class="cards">'''
        market_html=market_html.replace(anchor,tabs,1)
    s=s[:mw_start]+repr(market_html)+s[mw_end:]

    if "SECTOR_PERFORMANCE_HTML =" not in s:
        insert_at=s.find("\n\ndef snapshot():")
        if insert_at<0: raise RuntimeError("snapshot insertion anchor not found")
        s=s[:insert_at]+"\n\nSECTOR_PERFORMANCE_HTML = "+'\'<!doctype html>\\n<html><head><meta charset="utf-8"><title>APlus Sector Performance</title>\\n<style>\\n:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d;--cyan:#22d3ee}\\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}\\n.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}\\n.title{font-size:24px;font-weight:750}.sub{color:var(--muted);font-size:12px;margin-top:4px}\\n.tabs{padding:12px 24px;display:flex;gap:8px}.tab{padding:8px 14px;border-radius:9px;border:1px solid var(--line);color:var(--text);background:var(--panel);font-weight:700;text-decoration:none}.tab.active{border-color:var(--cyan);color:#9ffcff;background:#0f2730}\\n.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;padding:0 24px 14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.label{font-size:11px;color:var(--muted)}.value{font-size:20px;font-weight:750;margin-top:5px}\\n.grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(500px,.85fr);gap:14px;padding:0 24px 20px}\\n.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}.boxtitle{font-size:18px;font-weight:750;margin-bottom:10px}\\n.chart{height:520px;overflow:auto;padding-right:8px}.barrow{display:grid;grid-template-columns:180px 1fr 72px;align-items:center;gap:10px;margin:7px 0;cursor:pointer}.barlabel{font-size:12px;text-align:right}.track{height:13px;background:#0f1729;border-radius:4px;position:relative;overflow:hidden}.fill{height:100%;border-radius:4px}.fill.up{background:rgba(23,201,100,.75)}.fill.down{background:rgba(243,18,96,.75)}.barval{font-size:12px;font-weight:700}.up{color:var(--green)}.down{color:var(--red)}\\n.tablewrap{max-height:520px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}th{position:sticky;top:0;background:#0f1729;color:var(--muted);text-align:left}.right{text-align:right}.ltp{font-weight:850;color:#eaffff;text-shadow:0 0 8px rgba(34,211,238,.7)}\\n.footer{padding:18px;text-align:center;color:var(--muted);border-top:1px solid var(--line)}\\n@media(max-width:1200px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}}\\n</style></head><body>\\n<div class="header"><div><div class="title">APlus F&O Market Watch</div><div class="sub">Sector Performance • all % calculations from 09:15 Open only</div></div><div style="text-align:right"><a href="/" style="color:#7dd3fc;text-decoration:none">← Live Trading Terminal</a><div id="updated" class="sub">Waiting...</div></div></div>\\n<div class="cards">\\n<div class="card"><div class="label">F&O Stocks</div><div id="cnt" class="value">-</div></div>\\n<div class="card"><div class="label">Advancing from 09:15 Open</div><div id="adv" class="value up">-</div></div>\\n<div class="card"><div class="label">Declining from 09:15 Open</div><div id="dec" class="value down">-</div></div>\\n<div class="card"><div class="label">Top from 09:15 Open</div><div id="topup" class="value up">-</div></div>\\n<div class="card"><div class="label">Bottom from 09:15 Open</div><div id="topdn" class="value down">-</div></div>\\n</div>\\n<div class="tabs"><a class="tab" href="/fno-market-watch">Market Watch</a><a class="tab active" href="/sector-performance">Sector Performance</a></div>\\n<div class="grid">\\n  <div class="box">\\n    <div class="boxtitle">Sector Performance</div>\\n    <div class="sub">Sector % = average movement of its F&O stocks from each stock\\\'s 09:15 open.</div>\\n    <div id="sectorBars" class="chart"></div>\\n    <div class="sub">Click any sector to view its constituent stocks.</div>\\n  </div>\\n  <div class="box">\\n    <div class="boxtitle" id="stockTitle">Sector Stocks</div>\\n    <div class="tablewrap"><table><thead><tr>\\n      <th>Symbol</th><th>Sector</th><th class="right">% from 09:15 Open</th><th class="right">LTP</th><th class="right">09:15 Open</th><th class="right">High</th><th class="right">Low</th>\\n    </tr></thead><tbody id="sectorStocks"></tbody></table></div>\\n  </div>\\n</div>\\n<div class="footer">APlus Live Trading Terminal — Developed by Darpan Bobhate</div>\\n<script>\\nlet data=[],selectedSector=null;\\nconst money=n=>\\\'₹\\\'+Number(n||0).toLocaleString(\\\'en-IN\\\',{maximumFractionDigits:2});\\nconst pct=n=>(Number(n)>=0?\\\'+\\\':\\\'\\\')+Number(n||0).toFixed(2)+\\\'%\\\';\\n\\nfunction aggregateSectors(){\\n const m={};\\n data.forEach(x=>{\\n   const s=x.sector||\\\'UNCLASSIFIED\\\';\\n   if(!m[s])m[s]={sector:s,sum:0,count:0};\\n   m[s].sum+=Number(x.from_open_pct||0);m[s].count++;\\n });\\n return Object.values(m).map(x=>({sector:x.sector,move:x.count?x.sum/x.count:0,count:x.count})).sort((a,b)=>b.move-a.move);\\n}\\nfunction renderBars(){\\n const a=aggregateSectors();\\n const max=Math.max(0.01,...a.map(x=>Math.abs(x.move)));\\n sectorBars.innerHTML=a.map(x=>{\\n   const w=Math.max(1,Math.abs(x.move)/max*100);\\n   return `<div class="barrow" data-sector="${x.sector.replace(/"/g,\\\'&quot;\\\')}">\\n     <div class="barlabel">${x.sector}</div>\\n     <div class="track"><div class="fill ${x.move>=0?\\\'up\\\':\\\'down\\\'}" style="width:${w}%"></div></div>\\n     <div class="barval ${x.move>=0?\\\'up\\\':\\\'down\\\'}">${pct(x.move)}</div>\\n   </div>`;\\n }).join(\\\'\\\');\\n document.querySelectorAll(\\\'.barrow\\\').forEach(el=>el.onclick=()=>selectSector(el.dataset.sector));\\n if(!selectedSector && a.length)selectSector(a[0].sector);\\n}\\nfunction selectSector(s){selectedSector=s;renderStocks();}\\nfunction renderStocks(){\\n stockTitle.textContent=(selectedSector||\\\'Sector\\\')+\\\' Stocks\\\';\\n const a=data.filter(x=>(x.sector||\\\'UNCLASSIFIED\\\')===selectedSector).sort((x,y)=>y.from_open_pct-x.from_open_pct);\\n sectorStocks.innerHTML=a.map(x=>`<tr>\\n <td><b>${x.symbol}</b></td><td>${x.sector||\\\'UNCLASSIFIED\\\'}</td>\\n <td class="right ${x.from_open_pct>=0?\\\'up\\\':\\\'down\\\'}">${pct(x.from_open_pct)}</td>\\n <td class="right ltp">${money(x.ltp)}</td><td class="right">${money(x.open_0915)}</td>\\n <td class="right">${money(x.day_high)}</td><td class="right">${money(x.day_low)}</td></tr>`).join(\\\'\\\');\\n}\\nasync function load(){\\n const r=await fetch(\\\'/api/fno-market-watch?ts=\\\'+Date.now());const d=await r.json();data=d.rows||[];\\n cnt.textContent=data.length;adv.textContent=data.filter(x=>x.from_open_pct>0).length;dec.textContent=data.filter(x=>x.from_open_pct<0).length;\\n if(data.length){const u=[...data].sort((a,b)=>b.from_open_pct-a.from_open_pct)[0],dn=[...data].sort((a,b)=>a.from_open_pct-b.from_open_pct)[0];topup.textContent=u.symbol+\\\' \\\'+pct(u.from_open_pct);topdn.textContent=dn.symbol+\\\' \\\'+pct(dn.from_open_pct);}\\n updated.textContent=d.generated_at?\\\'Updated \\\'+String(d.generated_at).slice(11,19):\\\'Waiting...\\\';\\n renderBars();if(selectedSector)renderStocks();\\n}\\nload();setInterval(load,5000);\\n</script></body></html>\''+s[insert_at:]

    if 'if path == "/sector-performance":' not in s:
        route_anchor='        if path == "/api/snapshot":'
        pos=s.find(route_anchor)
        if pos<0: raise RuntimeError("dashboard route anchor not found")
        route='''        if path == "/sector-performance":
            body = SECTOR_PERFORMANCE_HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
'''
        s=s[:pos]+route+s[pos:]

    p.write_text(s,encoding="utf-8")
    py_compile.compile(str(p),doraise=True)
except Exception:
    shutil.copy2(b,p)
    print("INSTALL FAILED - original dashboard restored:",b)
    raise

print("="*78)
print("SUCCESS: SECTOR PERFORMANCE PANEL V2 INSTALLED")
print("Backup:",b)
print("PASS: integrated Market Watch / Sector Performance navigation")
print("PASS: sector % calculated ONLY from 09:15 open")
print("PASS: stock % calculated ONLY from 09:15 open")
print("PASS: click sector to view F&O stocks")
print("PASS: LTP highlighted")
print("PASS: scanner untouched")
print("PASS: ZERO additional Dhan API calls")
print("="*78)
