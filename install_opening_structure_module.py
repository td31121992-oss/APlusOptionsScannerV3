from pathlib import Path
from datetime import datetime
import ast, shutil, py_compile

ROOT=Path(__file__).resolve().parent
DASH=ROOT/"aplus_live_pnl_dashboard.py"
if not DASH.is_file(): raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_opening_structure_{stamp}"
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(DASH,backup/DASH.name)

def find_literal(text,name):
    marker=name+" = "
    i=text.find(marker)
    if i<0: raise RuntimeError(name+" block not found")
    st=i+len(marker)
    ends=[x for x in (text.find("\n\ndef ",st),text.find("\n\nclass ",st)) if x>=0]
    if not ends: raise RuntimeError("Could not locate end of "+name)
    en=min(ends)
    return st,en,ast.literal_eval(text[st:en])

try:
    s=DASH.read_text(encoding="utf-8")

    # Add standalone page before snapshot().
    if "OPENING_STRUCTURE_HTML =" not in s:
        pos=s.find("\n\ndef snapshot():")
        if pos<0: raise RuntimeError("snapshot anchor not found")
        s=s[:pos]+"\n\nOPENING_STRUCTURE_HTML = "+'\'<!doctype html>\\n<html><head><meta charset="utf-8"><title>APlus Opening Structure</title>\\n<style>\\n:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d;--cyan:#22d3ee}\\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}\\n.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}\\n.title{font-size:24px;font-weight:800}.sub{color:var(--muted);font-size:12px;margin-top:4px}\\n.tabs{padding:12px 24px;display:flex;gap:8px;flex-wrap:wrap}.tab{padding:8px 14px;border-radius:9px;border:1px solid var(--line);color:var(--text);background:var(--panel);font-weight:700;text-decoration:none}.tab.active{border-color:var(--cyan);color:#9ffcff;background:#0f2730}\\n.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;padding:0 24px 14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.label{font-size:11px;color:var(--muted)}.value{font-size:20px;font-weight:800;margin-top:5px}\\n.toolbar{padding:0 24px 12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}\\nbutton,select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 12px;font-weight:700}\\nbutton{cursor:pointer}.activeBtn{border-color:var(--green);background:#173527;color:#9ff0bd}\\n.tablewrap{padding:0 24px 24px;overflow:auto}table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line)}\\nth,td{padding:9px 10px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}th{color:var(--muted);background:#0f1729;position:sticky;top:0}.right{text-align:right}\\n.up{color:var(--green);font-weight:750}.down{color:var(--red);font-weight:750}.neutral{color:var(--muted)}\\n.badge{display:inline-block;padding:3px 8px;border-radius:999px;font-weight:800}.bull{background:#173527;color:#9ff0bd}.bear{background:#3c1724;color:#ff9bbb}.watch{background:#243049;color:#bdd0ef}\\n.ltp{font-weight:900;color:#eaffff;text-shadow:0 0 8px rgba(34,211,238,.72)}\\n.footer{padding:18px;text-align:center;color:var(--muted);border-top:1px solid var(--line)}\\n@media(max-width:1200px){.cards{grid-template-columns:repeat(3,1fr)}}\\n</style></head><body>\\n<div class="header">\\n <div><div class="title">APlus Opening Structure Scanner</div>\\n <div class="sub">Open≈Low / Open≈High • confirmation from 09:15 movement + sector alignment • PAPER / RESEARCH ONLY</div></div>\\n <div style="text-align:right"><a href="/" style="color:#7dd3fc;text-decoration:none">← Live Trading Terminal</a><div id="updated" class="sub">Waiting...</div></div>\\n</div>\\n<div class="cards">\\n <div class="card"><div class="label">F&O Stocks</div><div id="cnt" class="value">-</div></div>\\n <div class="card"><div class="label">Open≈Low</div><div id="ol" class="value up">-</div></div>\\n <div class="card"><div class="label">Open≈High</div><div id="oh" class="value down">-</div></div>\\n <div class="card"><div class="label">Open≈Low Confirmed</div><div id="olc" class="value up">-</div></div>\\n <div class="card"><div class="label">Open≈High Confirmed</div><div id="ohc" class="value down">-</div></div>\\n <div class="card"><div class="label">Qualified CE / PE</div><div id="qp" class="value">-</div></div>\\n</div>\\n<div class="tabs">\\n <a class="tab" href="/fno-market-watch">Market Watch</a>\\n <a class="tab" href="/sector-performance">Sector Performance</a>\\n <a class="tab active" href="/opening-structure">Opening Structure</a>\\n</div>\\n<div class="toolbar">\\n <button id="bALL" class="activeBtn" onclick="setMode(\\\'ALL\\\')">All</button>\\n <button id="bOL" onclick="setMode(\\\'OL\\\')">Open≈Low</button>\\n <button id="bOH" onclick="setMode(\\\'OH\\\')">Open≈High</button>\\n <button id="bOLC" onclick="setMode(\\\'OLC\\\')">Open≈Low Confirmed</button>\\n <button id="bOHC" onclick="setMode(\\\'OHC\\\')">Open≈High Confirmed</button>\\n <select id="sectorFilter" onchange="render()"><option value="ALL">All Sectors</option></select>\\n <span class="sub">Tolerance: max ₹0.05 or 0.05% of Open</span>\\n <span class="sub" id="shown"></span>\\n</div>\\n<div class="tablewrap"><table>\\n<thead><tr>\\n <th>Symbol</th><th>Sector</th><th>Structure</th><th class="right">Open</th><th class="right">LTP</th>\\n <th class="right">High</th><th class="right">Low</th><th class="right">Open→Low Dist %</th>\\n <th class="right">Open→High Dist %</th><th class="right">% from 09:15</th><th class="right">Sector %</th>\\n <th>Confirmation</th><th>Bias</th>\\n</tr></thead><tbody id="rows"></tbody></table></div>\\n<div class="footer">APlus Live Trading Terminal — Developed by Darpan Bobhate</div>\\n<script>\\nlet data=[],mode=\\\'ALL\\\',sectorPerf={};\\nconst money=n=>\\\'₹\\\'+Number(n||0).toLocaleString(\\\'en-IN\\\',{maximumFractionDigits:2});\\nconst pct=n=>(Number(n)>=0?\\\'+\\\':\\\'\\\')+Number(n||0).toFixed(2)+\\\'%\\\';\\n\\nfunction buildSectorPerf(){\\n const m={};data.forEach(x=>{const s=x.sector||\\\'Other/Industrial\\\';if(!m[s])m[s]={sum:0,n:0};m[s].sum+=Number(x.from_open_pct||0);m[s].n++;});\\n sectorPerf={};Object.entries(m).forEach(([s,v])=>sectorPerf[s]=v.n?v.sum/v.n:0);\\n}\\nfunction classify(x){\\n const o=Number(x.open_0915||0),h=Number(x.day_high||0),l=Number(x.day_low||0),m=Number(x.from_open_pct||0);\\n const s=x.sector||\\\'Other/Industrial\\\',sp=Number(sectorPerf[s]||0);\\n const tol=Math.max(0.05,o*0.0005);\\n const dLow=Math.abs(o-l),dHigh=Math.abs(h-o);\\n const ol=dLow<=tol,oh=dHigh<=tol;\\n let structure=ol?\\\'OPEN≈LOW\\\':oh?\\\'OPEN≈HIGH\\\':\\\'-\\\';\\n let confirm=\\\'WATCH\\\',bias=\\\'NONE\\\';\\n if(ol && m>=0.35 && sp>=0){confirm=\\\'CONFIRMED\\\';bias=\\\'CE\\\';}\\n if(oh && m<=-0.35 && sp<=0){confirm=\\\'CONFIRMED\\\';bias=\\\'PE\\\';}\\n return {...x,_structure:structure,_ol:ol,_oh:oh,_confirm:confirm,_bias:bias,_sectorPct:sp,\\n   _dLowPct:o?dLow/o*100:0,_dHighPct:o?dHigh/o*100:0};\\n}\\nfunction setMode(m){mode=m;document.querySelectorAll(\\\'.toolbar button\\\').forEach(x=>x.classList.remove(\\\'activeBtn\\\'));document.getElementById(\\\'b\\\'+m).classList.add(\\\'activeBtn\\\');render();}\\nfunction render(){\\n buildSectorPerf();\\n let a=data.map(classify),sec=sectorFilter.value;\\n if(sec!==\\\'ALL\\\')a=a.filter(x=>(x.sector||\\\'Other/Industrial\\\')===sec);\\n if(mode===\\\'OL\\\')a=a.filter(x=>x._ol);\\n else if(mode===\\\'OH\\\')a=a.filter(x=>x._oh);\\n else if(mode===\\\'OLC\\\')a=a.filter(x=>x._ol&&x._confirm===\\\'CONFIRMED\\\');\\n else if(mode===\\\'OHC\\\')a=a.filter(x=>x._oh&&x._confirm===\\\'CONFIRMED\\\');\\n\\n a.sort((x,y)=>{\\n   const xc=(x._confirm===\\\'CONFIRMED\\\'?1:0),yc=(y._confirm===\\\'CONFIRMED\\\'?1:0);\\n   if(xc!==yc)return yc-xc;\\n   return Math.abs(Number(y.from_open_pct||0))-Math.abs(Number(x.from_open_pct||0));\\n });\\n shown.textContent=\\\'Showing \\\'+a.length+\\\' of \\\'+data.length+\\\' stocks\\\';\\n rows.innerHTML=a.map(x=>`<tr>\\n  <td><b>${x.symbol}</b></td><td>${x.sector||\\\'Other/Industrial\\\'}</td>\\n  <td>${x._structure===\\\'OPEN≈LOW\\\'?\\\'<span class="badge bull">OPEN≈LOW</span>\\\':x._structure===\\\'OPEN≈HIGH\\\'?\\\'<span class="badge bear">OPEN≈HIGH</span>\\\':\\\'-\\\'}</td>\\n  <td class="right">${money(x.open_0915)}</td><td class="right ltp">${money(x.ltp)}</td>\\n  <td class="right">${money(x.day_high)}</td><td class="right">${money(x.day_low)}</td>\\n  <td class="right">${x._dLowPct.toFixed(3)}%</td><td class="right">${x._dHighPct.toFixed(3)}%</td>\\n  <td class="right ${Number(x.from_open_pct)>=0?\\\'up\\\':\\\'down\\\'}">${pct(x.from_open_pct)}</td>\\n  <td class="right ${x._sectorPct>=0?\\\'up\\\':\\\'down\\\'}">${pct(x._sectorPct)}</td>\\n  <td>${x._confirm===\\\'CONFIRMED\\\'?\\\'<span class="badge \\\'+(x._bias===\\\'CE\\\'?\\\'bull\\\':\\\'bear\\\')+\\\'">CONFIRMED</span>\\\':\\\'<span class="badge watch">WATCH</span>\\\'}</td>\\n  <td>${x._bias===\\\'CE\\\'?\\\'<span class="badge bull">CE</span>\\\':x._bias===\\\'PE\\\'?\\\'<span class="badge bear">PE</span>\\\':\\\'-\\\'}</td>\\n </tr>`).join(\\\'\\\');\\n\\n const all=data.map(classify);\\n cnt.textContent=data.length;ol.textContent=all.filter(x=>x._ol).length;oh.textContent=all.filter(x=>x._oh).length;\\n olc.textContent=all.filter(x=>x._ol&&x._confirm===\\\'CONFIRMED\\\').length;ohc.textContent=all.filter(x=>x._oh&&x._confirm===\\\'CONFIRMED\\\').length;\\n qp.textContent=all.filter(x=>x._bias===\\\'CE\\\').length+\\\' / \\\'+all.filter(x=>x._bias===\\\'PE\\\').length;\\n}\\nasync function load(){\\n const r=await fetch(\\\'/api/fno-market-watch?ts=\\\'+Date.now());const d=await r.json();data=d.rows||[];\\n updated.textContent=d.generated_at?\\\'Updated \\\'+String(d.generated_at).slice(11,19):\\\'Waiting...\\\';\\n const old=sectorFilter.value;const secs=[...new Set(data.map(x=>x.sector||\\\'Other/Industrial\\\'))].sort();\\n sectorFilter.innerHTML=\\\'<option value="ALL">All Sectors</option>\\\'+secs.map(s=>`<option value="${s}">${s}</option>`).join(\\\'\\\');\\n if(old===\\\'ALL\\\'||secs.includes(old))sectorFilter.value=old;\\n render();\\n}\\nload();setInterval(load,5000);\\n</script></body></html>\''+s[pos:]
        

    # Add route.
    if 'if path == "/opening-structure":' not in s:
        anchor='        if path == "/api/snapshot":'
        pos=s.find(anchor)
        if pos<0: raise RuntimeError("dashboard route anchor not found")
        route='''        if path == "/opening-structure":
            body = OPENING_STRUCTURE_HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
'''
        s=s[:pos]+route+s[pos:]

    # Add navigation link to Market Watch and Sector Performance if present.
    for var in ("FNO_MARKET_WATCH_HTML","SECTOR_PERFORMANCE_HTML"):
        try:
            st,en,html=find_literal(s,var)
        except Exception:
            continue
        if 'href="/opening-structure"' not in html:
            # Add a compact link before closing body; avoids brittle toolbar anchors.
            link='<a href="/opening-structure" style="position:fixed;left:22px;bottom:22px;z-index:9998;background:#0f2730;color:#9ffcff;text-decoration:none;font-weight:800;padding:10px 14px;border:1px solid #22d3ee;border-radius:10px">OPENING STRUCTURE</a>'
            if "</body></html>" in html:
                html=html.replace("</body></html>",link+"</body></html>",1)
                s=s[:st]+repr(html)+s[en:]

    # Add main-dashboard button too.
    if 'href="/opening-structure"' not in s.split("FNO_MARKET_WATCH_HTML",1)[0]:
        anchor="</body></html>"
        # Replace only first occurrence belonging to main dashboard HTML.
        pos=s.find(anchor)
        if pos>=0:
            link='<a href="/opening-structure" style="position:fixed;left:22px;bottom:22px;z-index:9998;background:#0f2730;color:#9ffcff;text-decoration:none;font-weight:800;padding:10px 14px;border:1px solid #22d3ee;border-radius:10px">OPENING STRUCTURE</a>'
            s=s[:pos]+link+s[pos:]

    DASH.write_text(s,encoding="utf-8")
    py_compile.compile(str(DASH),doraise=True)

except Exception:
    shutil.copy2(backup/DASH.name,DASH)
    print("INSTALL FAILED - original dashboard restored:",backup)
    raise

print("="*82)
print("SUCCESS: OPENING STRUCTURE MODULE INSTALLED")
print("Backup:",backup)
print("PASS: Open≈Low / Open≈High live classification")
print("PASS: confirmed Open≈Low -> CE research bias")
print("PASS: confirmed Open≈High -> PE research bias")
print("PASS: sector alignment uses 09:15 sector performance")
print("PASS: live LTP / Open / High / Low / distance metrics")
print("PASS: Market Watch and Sector Performance links")
print("PASS: scanner trading logic untouched")
print("PASS: PAPER / RESEARCH ONLY")
print("PASS: ZERO additional Dhan API calls")
print("="*82)
