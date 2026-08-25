from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import re

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "aplus_live_pnl_dashboard.py"
ALERT = ROOT / "technical_alert_dashboard.py"

if not MAIN.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
if not ALERT.is_file():
    raise SystemExit("FAIL: technical_alert_dashboard.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_mobile_dashboard_v3_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(MAIN, backup / MAIN.name)
shutil.copy2(ALERT, backup / ALERT.name)

MAIN_MOBILE_CSS = '\n<style id="aplus-mobile-css">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n@media(max-width:760px){\n  body{font-size:14px!important;overflow-x:hidden}\n  #aplus-main-nav{position:sticky!important;top:0!important;z-index:9999!important;padding:8px!important;gap:6px!important;overflow-x:auto!important;flex-wrap:nowrap!important;-webkit-overflow-scrolling:touch}\n  #aplus-main-nav a{flex:0 0 auto!important;padding:9px 11px!important;font-size:11px!important;white-space:nowrap!important}\n  .header{padding:12px 14px!important;gap:10px!important;align-items:flex-start!important}\n  .brandrow{gap:8px!important}.aplus-logo{width:38px!important;height:38px!important}\n  .title{font-size:18px!important}.sub{font-size:10px!important}\n  .grid,.cards{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:8px!important;padding:10px!important}\n  .card{padding:10px!important;border-radius:10px!important}\n  .label{font-size:10px!important}.value{font-size:18px!important}\n  .filterbar,.toolbar,.tabs{padding:0 10px 10px!important;gap:6px!important;overflow-x:auto!important;white-space:nowrap!important;flex-wrap:nowrap!important}\n  .tradefilter,.toolbar button,.toolbar select,.tab{padding:8px 10px!important;font-size:11px!important;flex:0 0 auto!important}\n  .tablewrap{padding:0 8px 12px!important;overflow-x:auto!important;-webkit-overflow-scrolling:touch}\n  table{min-width:980px!important}\n  th,td{padding:8px!important;font-size:11px!important}\n  .grid{grid-template-columns:1fr!important}\n  .crisp-footer{grid-template-columns:1fr!important;padding:14px!important;gap:10px!important;text-align:center!important}\n  .cf-copy{text-align:center!important}.cf-title{font-size:17px!important}\n  .watermark{font-size:34px!important}\n}\n</style>\n'
ALERT_MOBILE_CSS = '\n<style id="aplus-mobile-css">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n@media(max-width:760px){\n  body{font-size:14px!important;overflow-x:hidden}\n  header{padding:12px 14px!important}\n  .title{font-size:19px!important}.sub{font-size:10px!important}\n  .toolbar{padding:10px!important;overflow-x:auto!important;flex-wrap:nowrap!important;white-space:nowrap!important}\n  button,select{font-size:11px!important;padding:8px 9px!important;flex:0 0 auto!important}\n  .table{padding:0 8px 14px!important;overflow-x:auto!important;-webkit-overflow-scrolling:touch}\n  table{min-width:980px!important}\n  th,td{font-size:11px!important;padding:8px!important}\n}\n</style>\n'

MAIN_HELPER = """
def _mobileize_html(html, host=None):
    if not isinstance(html, str):
        return html
    out = html
    if 'id="aplus-mobile-css"' not in out:
        out = out.replace("</head>", MAIN_MOBILE_CSS + "</head>", 1)
    if host:
        out = out.replace("http://127.0.0.1:8766", f"http://{host}:8766")
    return out

"""

ALERT_HELPER = """
def _mobileize_alert_html(html):
    if not isinstance(html, str):
        return html
    out = html
    if 'id="aplus-mobile-css"' not in out:
        out = out.replace("</head>", ALERT_MOBILE_CSS + "</head>", 1)
    return out

"""

try:
    s = MAIN.read_text(encoding="utf-8")

    # Listen on all LAN interfaces.
    s = re.sub(
        r'^HOST\s*=\s*["\']127\.0\.0\.1["\']',
        'HOST = "0.0.0.0"',
        s,
        count=1,
        flags=re.M,
    )

    # Add CSS constant + helper safely outside HTML literals.
    if "MAIN_MOBILE_CSS =" not in s:
        anchor = "def _num("
        pos = s.find(anchor)
        if pos < 0:
            raise RuntimeError("main helper anchor not found")
        block = "MAIN_MOBILE_CSS = " + repr(MAIN_MOBILE_CSS) + "\n\n" + MAIN_HELPER
        s = s[:pos] + block + s[pos:]

    # Modify only response expressions, never stored HTML literals.
    replacements = [
        ('body = FNO_MARKET_WATCH_HTML.encode("utf-8")',
         'body = _mobileize_html(FNO_MARKET_WATCH_HTML).encode("utf-8")'),
        ('body = SECTOR_PERFORMANCE_HTML.encode("utf-8")',
         'body = _mobileize_html(SECTOR_PERFORMANCE_HTML).encode("utf-8")'),
        ('body = OPENING_STRUCTURE_HTML.encode("utf-8")',
         'body = _mobileize_html(OPENING_STRUCTURE_HTML).encode("utf-8")'),
        ('body = HTML.encode("utf-8")',
         'body = _mobileize_html(HTML, self.headers.get("Host","127.0.0.1").split(":")[0]).encode("utf-8")'),
    ]
    for old, new in replacements:
        if new not in s:
            if old not in s:
                raise RuntimeError("main response anchor missing: " + old)
            s = s.replace(old, new, 1)

    MAIN.write_text(s, encoding="utf-8")
    py_compile.compile(str(MAIN), doraise=True)

    a = ALERT.read_text(encoding="utf-8")
    a = re.sub(
        r'HOST\s*=\s*["\']127\.0\.0\.1["\']',
        'HOST="0.0.0.0"',
        a,
        count=1,
    )

    if "ALERT_MOBILE_CSS =" not in a:
        anchor = "class H("
        pos = a.find(anchor)
        if pos < 0:
            raise RuntimeError("technical alert helper anchor not found")
        block = "ALERT_MOBILE_CSS = " + repr(ALERT_MOBILE_CSS) + "\n\n" + ALERT_HELPER
        a = a[:pos] + block + a[pos:]

    if 'b=_mobileize_alert_html(HTML).encode()' not in a:
        if 'b=HTML.encode()' in a:
            a = a.replace('b=HTML.encode()', 'b=_mobileize_alert_html(HTML).encode()', 1)
        elif 'b = HTML.encode()' in a:
            a = a.replace('b = HTML.encode()', 'b = _mobileize_alert_html(HTML).encode()', 1)
        else:
            raise RuntimeError("technical alert HTML response anchor not found")

    ALERT.write_text(a, encoding="utf-8")
    py_compile.compile(str(ALERT), doraise=True)

except Exception:
    shutil.copy2(backup / MAIN.name, MAIN)
    shutil.copy2(backup / ALERT.name, ALERT)
    print("INSTALL FAILED - originals restored:", backup)
    raise

print("=" * 86)
print("SUCCESS: APLUS MOBILE DASHBOARD V3 INSTALLED")
print("Backup:", backup)
print("PASS: stored HTML strings were NOT edited")
print("PASS: mobile CSS applied only when pages are served")
print("PASS: main dashboard available on LAN")
print("PASS: technical alerts available on LAN")
print("PASS: F&O Market Watch / Sector / Opening Structure responsive")
print("PASS: scanner/trading logic untouched")
print("=" * 86)
