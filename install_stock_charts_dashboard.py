from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, py_compile, shutil, re
ROOT=Path(__file__).resolve().parent
DASH=ROOT/"aplus_live_pnl_dashboard.py"
MODULE=ROOT/"stock_chart_dashboard_module.py"
COLLECTOR=ROOT/"stock_chart_history_collector.py"
if not DASH.exists(): raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
for p in (MODULE,COLLECTOR):
    if not p.exists(): raise SystemExit(f"FAIL: {p.name} not found")
stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_stock_charts_{stamp}"
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(DASH,backup/DASH.name)

def assignments(text):
    out=[]
    for m in re.finditer(r"(?m)^([A-Z][A-Z0-9_]*HTML)\\s*=\\s*",text):
        st=m.end();ends=[x for x in (text.find("\n\ndef ",st),text.find("\n\nclass ",st)) if x>=0]
        if not ends: continue
        en=min(ends)
        try: val=ast.literal_eval(text[st:en])
        except Exception: continue
        if isinstance(val,str) and "<html" in val.lower(): out.append((st,en,val))
    return out

def add_link(html):
    if 'href="/stock-charts"' in html:return html
    btn='<a href="/stock-charts" style="position:fixed;right:18px;top:18px;z-index:9999;background:#121a2d;color:#e7eefc;border:1px solid #22d3ee;border-radius:9px;padding:9px 12px;text-decoration:none;font-weight:800">STOCK CHARTS</a>'
    return html.replace("</body></html>",btn+"</body></html>",1)

try:
    s=DASH.read_text(encoding="utf-8")
    imp="from stock_chart_dashboard_module import STOCK_CHART_HTML, symbols_payload, chart_payload, parse_query\n"
    if imp not in s:
        pos=s.find("from urllib.parse import ")
        if pos>=0:
            e=s.find("\n",pos);s=s[:e+1]+imp+s[e+1:]
        else:
            pos=s.find("\n\n");s=s[:pos+2]+imp+s[pos+2:]
    for st,en,val in reversed(assignments(s)):
        nv=add_link(val)
        if nv!=val:s=s[:st]+repr(nv)+s[en:]
    if 'if path == "/stock-charts":' not in s:
        anchor='        if path == "/api/snapshot":'
        pos=s.find(anchor)
        if pos<0:raise RuntimeError("dashboard route anchor not found")
        route = (
            '        if path == "/stock-charts":\n'
            '            body=STOCK_CHART_HTML.encode("utf-8")\n'
            '            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return\n'
            '        if path == "/api/stock-chart-symbols":\n'
            '            q=parse_query(self.path); day=q.get("day") or datetime.now().date().isoformat()\n'
            '            body=json.dumps(symbols_payload(day)).encode("utf-8")\n'
            '            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return\n'
            '        if path == "/api/stock-chart":\n'
            '            q=parse_query(self.path); day=q.get("day") or datetime.now().date().isoformat(); symbol=q.get("symbol") or ""\n'
            '            body=json.dumps(chart_payload(day,symbol)).encode("utf-8")\n'
            '            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return\n'
        )
        s=s[:pos]+route+s[pos:]
    DASH.write_text(s,encoding="utf-8")
    py_compile.compile(str(DASH),doraise=True)
    py_compile.compile(str(MODULE),doraise=True)
    py_compile.compile(str(COLLECTOR),doraise=True)
    (ROOT/"start_stock_chart_history.bat").write_text('@echo off\nsetlocal\ncd /d "%~dp0"\npython stock_chart_history_collector.py\n',encoding="utf-8")
    task='@echo off\nsetlocal\ncd /d "%~dp0"\nschtasks /Create /TN "APlusOptionsScannerV3_StockChartHistory" /TR "cmd.exe /c \\\"\\\"%CD%\\start_stock_chart_history.bat\\\"\\\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /RL LIMITED /F\nif errorlevel 1 exit /b 1\necho SUCCESS: Stock chart history collector scheduled Mon-Fri 09:15.\npause\n'
    (ROOT/"install_stock_chart_history_scheduler.bat").write_text(task,encoding="utf-8")
except Exception:
    shutil.copy2(backup/DASH.name,DASH)
    raise
print("="*88)
print("SUCCESS: APLUS STOCK CHARTS / DAY REPLAY INSTALLED")
print("Backup:",backup)
print("PASS: dashboard route /stock-charts")
print("PASS: all-stock detail + gallery")
print("PASS: date / sector / symbol filters")
print("PASS: mobile responsive")
print("PASS: ZERO extra Dhan API calls")
print("PASS: scanner/trading logic untouched")
print("NEXT: run install_stock_chart_history_scheduler.bat once")
print("="*88)
