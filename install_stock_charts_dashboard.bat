@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Stock Charts / Day Replay - One Go Installer
echo DASHBOARD ONLY + HISTORY COLLECTOR - ZERO Dhan API calls
echo ==============================================================================
python install_stock_charts_dashboard.py
if errorlevel 1 (
 echo INSTALL FAILED - dashboard restored automatically.
 pause
 exit /b 1
)
call install_stock_chart_history_scheduler.bat
echo.
echo Restart ONLY dashboard:
echo   run_live_pnl_dashboard.bat
echo Open:
echo   http://127.0.0.1:8765/stock-charts
pause
