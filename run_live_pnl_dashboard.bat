@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus Live Trading Terminal
echo ============================================================
start "" "http://127.0.0.1:8765"
python aplus_live_pnl_dashboard.py
pause
