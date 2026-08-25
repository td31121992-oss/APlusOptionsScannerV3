@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================================================
echo APlus Stock Selection V2 - Compatible One-Go Installer
echo PRESERVES API RELIABILITY FIX - PAPER ONLY - NO LIVE ORDERS
echo ==========================================================================================
python install_stock_selection_v2_compatible.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - originals restored automatically.
  pause
  exit /b 1
)
echo.
python verify_stock_selection_v2_compatible.py
if errorlevel 1 (
  echo.
  echo VERIFY FAILED - DO NOT START TOMORROW SCANNER UNTIL REVIEWED.
  pause
  exit /b 2
)
echo.
echo ==========================================================================================
echo SUCCESS - STOCK SELECTION V2 + API RELIABILITY READY
echo ==========================================================================================
echo Tomorrow audit:
echo   data\reports\intraday_stock_selection_v2.csv
echo   data\reports\intraday_stock_selection_v2_latest.json
echo.
echo Chart Engine V5 remains RESEARCH ONLY.
echo Tomorrow remains PAPER ONLY.
pause
