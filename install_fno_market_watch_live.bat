@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus F&O Market Watch - Existing Quote Batch Integration
echo ==============================================================================
echo NO EXTRA DHAN API CALLS
echo.
python install_fno_market_watch_live.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - originals restored automatically.
  pause
  exit /b 1
)
echo.
echo ==============================================================================
echo INSTALL COMPLETE
echo ==============================================================================
echo IMPORTANT:
echo The currently-running scanner has the old Python code already loaded.
echo To see live F&O Market Watch TODAY:
echo   1. Stop ONLY APlus scanner with Ctrl+C
echo   2. Start: run_intraday_movement.bat
echo   3. Close/restart ONLY dashboard CMD: run_live_pnl_dashboard.bat
echo   4. Open http://127.0.0.1:8765/fno-market-watch
echo.
echo Existing CAlphaTrader should NOT be touched.
pause
