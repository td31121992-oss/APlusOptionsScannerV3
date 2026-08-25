from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parent
P=ROOT/"data"/"reports"/"technical_alerts_latest.json"
HOST="0.0.0.0";PORT=8766
HTML=r"""<!doctype html><html><head><meta charset="utf-8"><title>APlus Technical Alerts</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--g:#17c964;--r:#f31260}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}.title{font-size:24px;font-weight:800}.sub{color:var(--muted);font-size:12px}
.toolbar{padding:12px 24px;display:flex;gap:8px;flex-wrap:wrap}button,select{background:var(--panel);color:var(--text);border:1px solid var(--line);padding:8px 12px;border-radius:9px}
.table{padding:0 24px 24px;overflow:auto}table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:9px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}th{color:var(--muted);position:sticky;top:0;background:#0f1729}.up{color:var(--g);font-weight:700}.down{color:var(--r);font-weight:700}.a{font-weight:900}
</style></head><body>
<header><div><div class="title">APlus Real-Time Technical Alerts</div><div class="sub">Exact event time • daily stock history • 09:15 context • latest first</div></div><div class="sub">Updated <span id="u">-</span></div></header>
<div class="toolbar"><select id="grade" onchange="render()"><option>ALL</option><option>A+ CONFLUENCE</option><option>STRONG</option><option>WATCH</option><option>INFO</option></select><select id="type" onchange="render()"><option>ALL</option></select><span id="count" class="sub"></span></div>
<div class="table"><table><thead><tr><th>Time</th><th>Grade</th><th>Symbol</th><th>Sector</th><th>Alert</th><th>Direction</th><th>LTP</th><th>Level</th><th>From 09:15</th><th>Sector %</th><th>RVOL</th><th>Bias</th></tr></thead><tbody id="rows"></tbody></table></div>
<script>
let A=[];const p=n=>(Number(n)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
function render(){let a=A,g=grade.value,t=type.value;if(g!='ALL')a=a.filter(x=>x.grade==g);if(t!='ALL')a=a.filter(x=>x.alert_type==t);count.textContent='Showing '+a.length+' of '+A.length;rows.innerHTML=a.map(x=>`<tr><td>${x.time}</td><td class="a">${x.grade}</td><td><b>${x.symbol}</b></td><td>${x.sector}</td><td>${x.alert_type}</td><td class="${x.direction=='BULLISH'?'up':'down'}">${x.direction}</td><td>₹${Number(x.ltp).toFixed(2)}</td><td>₹${Number(x.level).toFixed(2)}</td><td class="${x.from_0915_pct>=0?'up':'down'}">${p(x.from_0915_pct)}</td><td class="${x.sector_from_0915_pct>=0?'up':'down'}">${p(x.sector_from_0915_pct)}</td><td>${Number(x.relative_volume||0).toFixed(2)}x</td><td>${x.bias}</td></tr>`).join('')}
async function load(){let d=await (await fetch('/api?x='+Date.now())).json();A=d.alerts||[];u.textContent=(d.generated_at||'').slice(11,19);let old=type.value,types=[...new Set(A.map(x=>x.alert_type))].sort();type.innerHTML='<option>ALL</option>'+types.map(x=>`<option>${x}</option>`).join('');if(types.includes(old))type.value=old;render()}load();setInterval(load,5000);
</script></body></html>"""
ALERT_MOBILE_CSS = '\n<style id="aplus-mobile-css">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n@media(max-width:760px){\n  body{font-size:14px!important;overflow-x:hidden}\n  header{padding:12px 14px!important}\n  .title{font-size:19px!important}.sub{font-size:10px!important}\n  .toolbar{padding:10px!important;overflow-x:auto!important;flex-wrap:nowrap!important;white-space:nowrap!important}\n  button,select{font-size:11px!important;padding:8px 9px!important;flex:0 0 auto!important}\n  .table{padding:0 8px 14px!important;overflow-x:auto!important;-webkit-overflow-scrolling:touch}\n  table{min-width:980px!important}\n  th,td{font-size:11px!important;padding:8px!important}\n}\n</style>\n'


def _mobileize_alert_html(html):
    if not isinstance(html, str):
        return html
    out = html
    if 'id="aplus-mobile-css"' not in out:
        out = out.replace("</head>", ALERT_MOBILE_CSS + "</head>", 1)
    return out

class H(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api":
            try:b=P.read_bytes()
            except:b=b'{"alerts":[]}'
            self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(b);return
        b=_mobileize_alert_html(HTML).encode();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.end_headers();self.wfile.write(b)
if __name__=="__main__":
    print(f"Open http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST,PORT),H).serve_forever()
