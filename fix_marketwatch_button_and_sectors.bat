@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Market Watch Button and Sector Classification Fix
echo ==============================================================================
echo Uses NSE public classification lookup. No Dhan API calls are added.
echo.
python fix_marketwatch_button_and_sectors.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - originals restored automatically.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Restart ONLY dashboard CMD:
echo   run_live_pnl_dashboard.bat
echo.
echo Keep APlus scanner running.
pause
