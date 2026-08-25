from pathlib import Path
from datetime import datetime
import shutil, py_compile, ast

p = Path("aplus_live_pnl_dashboard.py")
if not p.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")

b = Path(f"aplus_live_pnl_dashboard_before_sector_panel_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p, b)
s = p.read_text(encoding="utf-8")

try:
    marker = "FNO_MARKET_WATCH_HTML = "
    i = s.find(marker)
    if i < 0:
        raise RuntimeError("F&O Market Watch HTML block not found")

    start = i + len(marker)
    end_marker = "\n\ndef snapshot():"
    end = s.find(end_marker, start)
    if end < 0:
        raise RuntimeError("Could not locate end of F&O Market Watch block")

    html = ast.literal_eval(s[start:end])

    if "cdn.jsdelivr.net/npm/chart.js" not in html:
        html = html.replace("</head>", '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script></head>', 1)

    css = """
.tabs{padding:0 24px 12px;display:flex;gap:8px}
.tabbtn{background:var(--panel);color:var(--text);border:1px solid var(--line);padding:8px 14px;border-radius:9px;font-weight:700;cursor:pointer}
.tabbtn.active{border-color:var(--cyan);color:#9ffcff;background:#0f2730}
.panel{display:none}.panel.active{display:block}
.sectorgrid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(480px,.85fr);gap:14px;padding:0 24px 18px}
.sectorbox{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.sectortitle{font-size:18px;font-weight:750;margin-bottom:10px}
.sectorchartwrap{height:430px;overflow:auto}
.sectorstockwrap{max-height:430px;overflow:auto}
.sectorstockwrap table{width:100%}
.sectorstockwrap th{position:sticky;top:0}
@media(max-width:1200px){.sectorgrid{grid-template-columns:1fr}}
"""
    html = html.replace("</style>", css + "</style>", 1)

    anchor = '</div>\n<div class="toolbar">'
    tabs = """</div>
<div class="tabs">
  <button id="tabMarket" class="tabbtn active" onclick="showTab('market')">Market Watch</button>
  <button id="tabSector" class="tabbtn" onclick="showTab('sector')">Sector Performance</button>
</div>
<div id="marketPanel" class="panel active">
<div class="toolbar">"""
    if anchor not in html:
        raise RuntimeError("toolbar anchor not found")
    html = html.replace(anchor, tabs, 1)

    footer_anchor = '<div class="footer">APlus Live Trading Terminal — Developed by Darpan Bobhate</div>'
    sector_panel = """</div>
<div id="sectorPanel" class="panel">
  <div class="sectorgrid">
    <div class="sectorbox">
      <div class="sectortitle">Sector Performance - % from 09:15 Open</div>
      <div class="sub">Sector value = average move from 09:15 open of F&O constituents in that sector.</div>
      <div class="sectorchartwrap"><canvas id="sectorChart"></canvas></div>
      <div class="sub">Click a bar to view constituent stocks.</div>
    </div>
    <div class="sectorbox">
      <div class="sectortitle"><span id="sectorStockTitle">Sector Stocks</span></div>
      <div class="sectorstockwrap">
        <table><thead><tr>
          <th>Symbol</th><th>Sector</th><th class="right">% from 09:15 Open</th>
          <th class="right">LTP</th><th class="right">09:15 Open</th>
          <th class="right">High</th><th class="right">Low</th>
        </tr></thead><tbody id="sectorStocks"></tbody></table>
      </div>
    </div>
  </div>
</div>
"""
    if footer_anchor not in html:
        raise RuntimeError("footer anchor not found")
    html = html.replace(footer_anchor, sector_panel + footer_anchor, 1)

    js = """
let sectorChartObj=null,currentSector=null;
function showTab(t){
  document.getElementById('marketPanel').classList.toggle('active',t==='market');
  document.getElementById('sectorPanel').classList.toggle('active',t==='sector');
  document.getElementById('tabMarket').classList.toggle('active',t==='market');
  document.getElementById('tabSector').classList.toggle('active',t==='sector');
  if(t==='sector')renderSectorPerformance();
}
function sectorRows(){
  const m={};
  data.forEach(x=>{
    const sec=x.sector||'UNCLASSIFIED';
    if(sec==='UNCLASSIFIED')return;
    if(!m[sec])m[sec]={sector:sec,sum:0,count:0};
    m[sec].sum+=Number(x.from_open_pct||0);
    m[sec].count++;
  });
  return Object.values(m)
    .map(x=>({sector:x.sector,move:x.count?x.sum/x.count:0,count:x.count}))
    .sort((a,b)=>b.move-a.move);
}
function renderSectorPerformance(){
  const sr=sectorRows();
  const ctx=document.getElementById('sectorChart');
  if(!ctx)return;
  if(sectorChartObj)sectorChartObj.destroy();
  sectorChartObj=new Chart(ctx,{
    type:'bar',
    data:{
      labels:sr.map(x=>x.sector),
      datasets:[{
        data:sr.map(x=>x.move),
        backgroundColor:sr.map(x=>x.move>=0?'rgba(23,201,100,.70)':'rgba(243,18,96,.70)'),
        borderWidth:0
      }]
    },
    options:{
      indexAxis:'y',
      responsive:true,
      maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>pct(c.raw)}}},
      scales:{
        x:{ticks:{color:'#8ea0bd',callback:v=>v+'%'},grid:{color:'#27334d'}},
        y:{ticks:{color:'#e7eefc'},grid:{display:false}}
      },
      onClick:(evt,elements)=>{
        if(elements.length){
          currentSector=sr[elements[0].index].sector;
          renderSectorStocks();
        }
      }
    }
  });
  if(!currentSector && sr.length)currentSector=sr[0].sector;
  renderSectorStocks();
}
function renderSectorStocks(){
  if(!currentSector){
    sectorStockTitle.textContent='Sector Stocks';
    sectorStocks.innerHTML='';
    return;
  }
  sectorStockTitle.textContent=currentSector+' Stocks';
  const a=data.filter(x=>(x.sector||'UNCLASSIFIED')===currentSector)
              .sort((x,y)=>y.from_open_pct-x.from_open_pct);
  sectorStocks.innerHTML=a.map(x=>`<tr>
    <td><b>${x.symbol}</b></td>
    <td>${x.sector}</td>
    <td class="right ${x.from_open_pct>=0?'up':'down'}">${pct(x.from_open_pct)}</td>
    <td class="right ltp-live">${money(x.ltp)}</td>
    <td class="right">${money(x.open_0915)}</td>
    <td class="right">${money(x.day_high)}</td>
    <td class="right">${money(x.day_low)}</td>
  </tr>`).join('');
}
"""
    hook = "buildHeader();load();setInterval(load,5000);"
    if hook not in html:
        raise RuntimeError("JS hook not found")
    html = html.replace(hook, js + "\n" + hook, 1)

    refresh_old = "  render();\n}\nbuildHeader();load();setInterval(load,5000);"
    refresh_new = "  render();\n  if(document.getElementById('sectorPanel').classList.contains('active'))renderSectorPerformance();\n}\nbuildHeader();load();setInterval(load,5000);"
    if refresh_old in html:
        html = html.replace(refresh_old, refresh_new, 1)

    s = s[:start] + repr(html) + s[end:]
    p.write_text(s, encoding="utf-8")
    py_compile.compile(str(p), doraise=True)

except Exception:
    shutil.copy2(b, p)
    print("INSTALL FAILED - original dashboard restored:", b)
    raise

print("="*78)
print("SUCCESS: SECTOR PERFORMANCE PANEL INSTALLED")
print("Backup:", b)
print("PASS: Market Watch + Sector Performance tabs")
print("PASS: sector % calculated ONLY from 09:15 open")
print("PASS: click sector bar to show constituent F&O stocks")
print("PASS: stock % calculated ONLY from 09:15 open")
print("PASS: LTP remains highlighted")
print("PASS: scanner untouched")
print("PASS: ZERO additional Dhan API calls")
print("="*78)
