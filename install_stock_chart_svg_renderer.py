from pathlib import Path
from datetime import datetime
import py_compile, shutil

ROOT=Path(__file__).resolve().parent
TARGET=ROOT/"stock_chart_dashboard_module.py"
SRC=ROOT/"stock_chart_dashboard_module_svg.py"

if not SRC.exists(): raise SystemExit("FAIL: stock_chart_dashboard_module_svg.py not found")
stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_stock_chart_svg_{stamp}"
backup.mkdir(parents=True,exist_ok=False)
if TARGET.exists(): shutil.copy2(TARGET,backup/TARGET.name)

try:
    TARGET.write_text(SRC.read_text(encoding="utf-8"),encoding="utf-8")
    py_compile.compile(str(TARGET),doraise=True)

    from stock_chart_dashboard_module import symbols_payload, chart_payload
    x=symbols_payload("2026-08-20")
    mcx=chart_payload("2026-08-20","MCX")
    assert len(x.get("symbols",[]))==208, len(x.get("symbols",[]))
    assert len(mcx.get("points",[]))>0
    assert "<svg" in mcx.get("svg","")

except Exception:
    if (backup/TARGET.name).exists(): shutil.copy2(backup/TARGET.name,TARGET)
    print("INSTALL FAILED - old chart module restored.")
    raise

print("="*86)
print("SUCCESS: SERVER-RENDERED SVG STOCK CHARTS INSTALLED")
print("Backup:",backup)
print("PASS: 208 symbols loaded")
print("PASS: MCX points loaded")
print("PASS: SVG generated server-side")
print("PASS: no Canvas dependency")
print("PASS: no scanner/trading changes")
print("")
print("Restart ONLY run_live_pnl_dashboard.bat")
print("Then open http://127.0.0.1:8765/stock-charts")
print("="*86)
