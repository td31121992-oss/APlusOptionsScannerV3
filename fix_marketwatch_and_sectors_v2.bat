@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Market Watch and Sector Classification Fix V2
echo ==============================================================================
echo Fast bulk classification. No Dhan API calls are added.
echo.
python fix_marketwatch_and_sectors_v2.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - originals restored automatically.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Keep scanner running.
echo Restart ONLY dashboard using run_live_pnl_dashboard.bat
pause
