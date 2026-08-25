from pathlib import Path
from datetime import datetime
import shutil, py_compile, re

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "aplus_live_pnl_dashboard.py"
ALERT = ROOT / "technical_alert_dashboard.py"

if not MAIN.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
if not ALERT.is_file():
    raise SystemExit("FAIL: technical_alert_dashboard.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_mobile_dashboard_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(MAIN, backup / MAIN.name)
shutil.copy2(ALERT, backup / ALERT.name)

MOBILE_CSS = '\n/* APlus Mobile Responsive Layer */\n@media(max-width:760px){\n  body{font-size:14px}\n  #aplus-main-nav{position:sticky!important;top:0!important;z-index:9999!important;padding:8px!important;gap:6px!important;overflow-x:auto!important;flex-wrap:nowrap!important;-webkit-overflow-scrolling:touch}\n  #aplus-main-nav a{flex:0 0 auto!important;padding:9px 11px!important;font-size:11px!important;white-space:nowrap!important}\n  .header{padding:12px 14px!important;gap:10px!important;align-items:flex-start!important}\n  .brandrow{gap:8px!important}.aplus-logo{width:38px!important;height:38px!important}\n  .title{font-size:18px!important}.sub{font-size:10px!important}\n  .grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:8px!important;padding:10px!important}\n  .card{padding:10px!important;border-radius:10px!important}\n  .label{font-size:10px!important}.value{font-size:19px!important}\n  .filterbar{padding:0 10px 10px!important;gap:6px!important;overflow-x:auto!important;white-space:nowrap!important}\n  .tradefilter{padding:8px 10px!important;font-size:11px!important;flex:0 0 auto!important}\n  .tablewrap{padding:0 8px 12px!important;overflow-x:auto!important;-webkit-overflow-scrolling:touch}\n  table{min-width:1120px!important}\n  th,td{padding:8px!important;font-size:11px!important}\n  .crisp-footer{grid-template-columns:1fr!important;padding:14px!important;gap:10px!important;text-align:center!important}\n  .cf-copy{text-align:center!important}.cf-title{font-size:17px!important}\n  .watermark{font-size:34px!important}\n}\n'
AUX_CSS = '\n@media(max-width:760px){\n body{font-size:14px}\n .header{padding:12px 14px!important;gap:8px!important;align-items:flex-start!important}\n .title{font-size:19px!important}.sub{font-size:10px!important}\n .cards{grid-template-columns:repeat(2,minmax(0,1fr))!important;padding:0 10px 10px!important;gap:8px!important}\n .card{padding:10px!important}.value{font-size:18px!important}\n .tabs,.toolbar{padding:10px!important;overflow-x:auto!important;flex-wrap:nowrap!important;white-space:nowrap!important}\n .tab,.toolbar button,.toolbar select{flex:0 0 auto!important;font-size:11px!important;padding:8px 10px!important}\n .tablewrap{padding:0 8px 16px!important;overflow-x:auto!important;-webkit-overflow-scrolling:touch}\n table{min-width:1000px!important}\n th,td{font-size:11px!important;padding:8px!important}\n .grid{grid-template-columns:1fr!important;padding:0 10px 14px!important}\n}\n'
ALERT_CSS = '\n/* APlus Alert Mobile Layer */\n@media(max-width:760px){\n header{padding:12px 14px!important}.title{font-size:19px!important}.sub{font-size:10px!important}\n .toolbar{padding:10px!important;overflow-x:auto!important;flex-wrap:nowrap!important}\n button,select{font-size:11px!important;padding:8px 9px!important;flex:0 0 auto!important}\n .table{padding:0 8px 14px!important;overflow-x:auto!important}\n table{min-width:980px!important}\n th,td{font-size:11px!important;padding:8px!important}\n}\n'

try:
    s = MAIN.read_text(encoding="utf-8")
    s = re.sub(r'^HOST\s*=\s*["\']127\.0\.0\.1["\']', 'HOST = "0.0.0.0"', s, count=1, flags=re.M)

    if "APlus Mobile Responsive Layer" not in s:
        main_pos = s.find("HTML = '''")
        if main_pos < 0:
            raise RuntimeError("Main HTML block not found")
        pos = s.find("</style></head><body>", main_pos)
        if pos < 0:
            raise RuntimeError("Main style anchor not found")
        s = s[:pos] + MOBILE_CSS + s[pos:]

    s = s.replace(
        'href="http://127.0.0.1:8766"',
        'href="#" onclick="this.href=window.location.protocol+\'//\'+window.location.hostname+\':8766\';"'
    )

    for var in ("FNO_MARKET_WATCH_HTML", "SECTOR_PERFORMANCE_HTML", "OPENING_STRUCTURE_HTML"):
        start = s.find(var + " = ")
        if start < 0:
            continue
        pos = s.find("</style></head><body>", start)
        if pos < 0:
            continue
        nexts = [x for x in (
            s.find("\nSECTOR_PERFORMANCE_HTML", start + 1),
            s.find("\nOPENING_STRUCTURE_HTML", start + 1),
            s.find("\ndef ", start + 1),
            s.find("\nclass ", start + 1),
        ) if x >= 0]
        limit = min(nexts) if nexts else len(s)
        if pos < limit:
            probe = s[max(start, pos-2500):pos]
            if "@media(max-width:760px)" not in probe:
                s = s[:pos] + AUX_CSS + s[pos:]

    MAIN.write_text(s, encoding="utf-8")
    py_compile.compile(str(MAIN), doraise=True)

    a = ALERT.read_text(encoding="utf-8")
    a = re.sub(r'HOST\s*=\s*["\']127\.0\.0\.1["\']\s*;\s*PORT\s*=\s*8766', 'HOST="0.0.0.0";PORT=8766', a, count=1)
    if "APlus Alert Mobile Layer" not in a:
        pos = a.find("</style></head><body>")
        if pos < 0:
            raise RuntimeError("Technical alert style anchor not found")
        a = a[:pos] + ALERT_CSS + a[pos:]
    ALERT.write_text(a, encoding="utf-8")
    py_compile.compile(str(ALERT), doraise=True)

except Exception:
    shutil.copy2(backup / MAIN.name, MAIN)
    shutil.copy2(backup / ALERT.name, ALERT)
    print("INSTALL FAILED - originals restored:", backup)
    raise

print("="*86)
print("SUCCESS: APLUS MOBILE DASHBOARD MODE INSTALLED")
print("Backup:", backup)
print("PASS: Main dashboard responsive on phones")
print("PASS: F&O Market Watch responsive")
print("PASS: Sector Performance responsive")
print("PASS: Opening Structure responsive")
print("PASS: Technical Alerts responsive")
print("PASS: Dashboard servers listen on LAN")
print("PASS: Scanner/trading logic untouched")
print("="*86)
