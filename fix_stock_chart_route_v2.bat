@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Stock Charts Route V2 Fix
echo DASHBOARD ONLY - SCANNER/TRADING LOGIC UNTOUCHED
echo ==============================================================================
python fix_stock_chart_route_v2.py
if errorlevel 1 (
 echo.
 echo FIX FAILED - original dashboard restored automatically.
 pause
 exit /b 1
)
echo.
python verify_stock_chart_route_v2.py
if errorlevel 1 (
 echo.
 echo VERIFY FAILED.
 pause
 exit /b 2
)
echo.
echo ==============================================================================
echo SUCCESS
echo ==============================================================================
echo Stop ONLY the current dashboard CMD with Ctrl+C.
echo Then run:
echo   run_live_pnl_dashboard.bat
echo Then open:
echo   http://127.0.0.1:8765/stock-charts
pause
