@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================================================
echo APlus Stock Selection V2 - FINAL Exact-Scanner One-Go Installer
echo PRESERVES API RELIABILITY FIX - PAPER ONLY - NO LIVE ORDERS
echo ==========================================================================================
python install_stock_selection_v2_final.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - originals restored automatically.
  echo DO NOT run the scanner until we review the error above.
  pause
  exit /b 1
)
echo.
echo ==========================================================================================
echo SUCCESS - STOCK SELECTION V2 READY
 echo Tomorrow audit files:
echo   data\reports\intraday_stock_selection_v2.csv
echo   data\reports\intraday_stock_selection_v2_latest.json
echo.
echo API reliability fix preserved. Chart Engine V5 remains research only.
echo Tomorrow remains PAPER ONLY - NO LIVE ORDERS.
echo ==========================================================================================
pause
