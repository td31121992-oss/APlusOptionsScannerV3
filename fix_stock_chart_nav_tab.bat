@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Stock Charts Navigation Tab Fix
echo DASHBOARD ONLY - NO SCANNER/TRADING CHANGES
echo ==============================================================================
python fix_stock_chart_nav_tab.py
if errorlevel 1 (
 echo.
 echo NAV FIX FAILED - original dashboard restored automatically.
 pause
 exit /b 1
)
echo.
python verify_stock_chart_nav_tab.py
if errorlevel 1 (
 echo.
 echo VERIFY FAILED.
 pause
 exit /b 2
)
echo.
echo SUCCESS.
echo Stop ONLY dashboard CMD with Ctrl+C, restart run_live_pnl_dashboard.bat,
echo then refresh http://127.0.0.1:8765
pause
