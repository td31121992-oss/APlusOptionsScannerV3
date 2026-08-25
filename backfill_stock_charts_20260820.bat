@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Stock Charts - Backfill Today From Existing Research History
echo ZERO Dhan API calls
echo ==============================================================================
python backfill_stock_charts_20260820.py
if errorlevel 1 (
 echo.
 echo BACKFILL FAILED.
 pause
 exit /b 1
)
echo.
echo Backfill complete.
echo Restart ONLY the dashboard CMD, then open:
echo   http://127.0.0.1:8765/stock-charts
pause
