from __future__ import annotations

from pathlib import Path
from datetime import datetime
import ast
import py_compile
import shutil

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "aplus_live_pnl_dashboard.py"
MODULE = ROOT / "stock_chart_dashboard_module.py"

if not DASH.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
if not MODULE.is_file():
    raise SystemExit("FAIL: stock_chart_dashboard_module.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_stock_chart_route_v2_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(DASH, backup / DASH.name)

ROUTE = '        # APlus Stock Charts / Day Replay routes\n        if path == "/stock-charts":\n            body = STOCK_CHART_HTML.encode("utf-8")\n            self.send_response(200)\n            self.send_header("Content-Type", "text/html; charset=utf-8")\n            self.send_header("Cache-Control", "no-store")\n            self.send_header("Content-Length", str(len(body)))\n            self.end_headers()\n            self.wfile.write(body)\n            return\n        if path == "/api/stock-chart-symbols":\n            q = parse_query(self.path)\n            day = q.get("day") or datetime.now().date().isoformat()\n            body = json.dumps(symbols_payload(day)).encode("utf-8")\n            self.send_response(200)\n            self.send_header("Content-Type", "application/json")\n            self.send_header("Cache-Control", "no-store")\n            self.send_header("Content-Length", str(len(body)))\n            self.end_headers()\n            self.wfile.write(body)\n            return\n        if path == "/api/stock-chart":\n            q = parse_query(self.path)\n            day = q.get("day") or datetime.now().date().isoformat()\n            symbol = q.get("symbol") or ""\n            body = json.dumps(chart_payload(day, symbol)).encode("utf-8")\n            self.send_response(200)\n            self.send_header("Content-Type", "application/json")\n            self.send_header("Cache-Control", "no-store")\n            self.send_header("Content-Length", str(len(body)))\n            self.end_headers()\n            self.wfile.write(body)\n            return\n'

def find_literal(text: str, varname: str):
    marker = varname + " = "
    i = text.find(marker)
    if i < 0:
        raise RuntimeError(f"{varname} assignment not found")
    st = i + len(marker)
    ends = [x for x in (text.find("\n\ndef ", st), text.find("\n\nclass ", st)) if x >= 0]
    if not ends:
        raise RuntimeError(f"Could not locate end of {varname}")
    en = min(ends)
    val = ast.literal_eval(text[st:en])
    if not isinstance(val, str) or "<html" not in val.lower():
        raise RuntimeError(f"{varname} is not an HTML string")
    return st, en, val

def ensure_imports(s: str) -> str:
    imp = (
        "from stock_chart_dashboard_module import "
        "STOCK_CHART_HTML, symbols_payload, chart_payload, parse_query\n"
    )
    if imp in s:
        return s
    marker = "from urllib.parse import "
    i = s.find(marker)
    if i >= 0:
        e = s.find("\n", i)
        return s[:e+1] + imp + s[e+1:]
    i = s.find("\n\n")
    if i < 0:
        raise RuntimeError("Could not find import insertion point")
    return s[:i+2] + imp + s[i+2:]

def ensure_main_nav(s: str) -> str:
    try:
        st, en, html = find_literal(s, "HTML")
    except Exception:
        return s

    if 'href="/stock-charts"' in html:
        return s

    link = (
        '<a href="/stock-charts" '
        'style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;'
        'color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">'
        'STOCK CHARTS</a>'
    )

    nav_id = html.find('id="aplus-main-nav"')
    if nav_id >= 0:
        close = html.find("</div>", nav_id)
        if close >= 0:
            html = html[:close] + link + html[close:]
            return s[:st] + repr(html) + s[en:]

    nav_cls = html.find('class="nav"')
    if nav_cls >= 0:
        close = html.find("</div>", nav_cls)
        if close >= 0:
            html = html[:close] + link + html[close:]
            return s[:st] + repr(html) + s[en:]

    fixed = (
        '<a href="/stock-charts" '
        'style="position:fixed;right:18px;top:76px;z-index:99999;'
        'background:#121a2d;color:#9ffcff;border:1px solid #22d3ee;'
        'border-radius:9px;padding:9px 12px;text-decoration:none;font-weight:800">'
        'STOCK CHARTS</a>'
    )
    if "</body></html>" not in html:
        raise RuntimeError("Main HTML closing body not found")
    html = html.replace("</body></html>", fixed + "</body></html>", 1)
    return s[:st] + repr(html) + s[en:]

def ensure_routes(s: str) -> str:
    if 'if path == "/stock-charts":' in s and 'if path == "/api/stock-chart":' in s:
        return s
    anchor = "        path = urlparse(self.path).path\n"
    i = s.find(anchor)
    if i < 0:
        raise RuntimeError("Handler path anchor not found")
    return s[:i+len(anchor)] + ROUTE + s[i+len(anchor):]

try:
    s = DASH.read_text(encoding="utf-8")

    if "from datetime import datetime" not in s:
        pos = s.find("\n\n")
        if pos < 0:
            raise RuntimeError("datetime import insertion point not found")
        s = s[:pos+2] + "from datetime import datetime\n" + s[pos+2:]

    s = ensure_imports(s)
    s = ensure_main_nav(s)
    s = ensure_routes(s)

    DASH.write_text(s, encoding="utf-8")
    py_compile.compile(str(DASH), doraise=True)
    py_compile.compile(str(MODULE), doraise=True)

    final = DASH.read_text(encoding="utf-8")
    required = [
        'if path == "/stock-charts":',
        'if path == "/api/stock-chart-symbols":',
        'if path == "/api/stock-chart":',
        "STOCK_CHART_HTML",
        "symbols_payload",
        "chart_payload",
    ]
    missing = [x for x in required if x not in final]
    if missing:
        raise RuntimeError("Post-install verification missing: " + repr(missing))

except Exception:
    shutil.copy2(backup / DASH.name, DASH)
    print("FIX FAILED - original dashboard restored automatically.")
    print("Backup:", backup)
    raise

print("=" * 88)
print("SUCCESS: STOCK CHART ROUTE V2 FIXED")
print("Backup:", backup)
print("PASS: /stock-charts route inserted directly after URL parsing")
print("PASS: stock-chart API routes inserted")
print("PASS: main dashboard STOCK CHARTS link added")
print("PASS: dashboard compiles")
print("PASS: scanner/trading logic untouched")
print("")
print("IMPORTANT:")
print("1. Stop ONLY the dashboard CMD with Ctrl+C")
print("2. Start run_live_pnl_dashboard.bat again")
print("3. Open http://127.0.0.1:8765/stock-charts")
print("=" * 88)
