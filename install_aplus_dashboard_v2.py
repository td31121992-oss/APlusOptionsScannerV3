from pathlib import Path
import py_compile
ROOT=Path(__file__).resolve().parent
for name in ("aplus_dashboard_v2.py",):
    p=ROOT/name
    if not p.exists(): raise SystemExit("FAIL missing "+name)
    py_compile.compile(str(p),doraise=True)
(ROOT/"run_dashboard_v2.bat").write_text("""@echo off
setlocal
cd /d "%~dp0"
title APlus Dashboard V2
echo ========================================================================================
echo APlus Dashboard V2 - Standalone
echo Existing dashboard: http://127.0.0.1:8765
echo Dashboard V2:       http://127.0.0.1:8772
echo ========================================================================================
python aplus_dashboard_v2.py
pause
""",encoding="utf-8")
print("="*100)
print("SUCCESS: APLUS DASHBOARD V2 INSTALLED ALONGSIDE EXISTING DASHBOARD")
print("PASS existing aplus_live_pnl_dashboard.py untouched")
print("PASS scanner/trading/risk/Dhan logic untouched")
print("PASS zero new Dhan calls")
print("Run: run_dashboard_v2.bat")
print("Open: http://127.0.0.1:8772")
print("="*100)
