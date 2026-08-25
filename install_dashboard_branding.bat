@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus Live Trading Terminal - Branding Patch
echo ============================================================
python install_dashboard_branding.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Close the existing dashboard window and run:
echo   run_live_pnl_dashboard.bat
pause
