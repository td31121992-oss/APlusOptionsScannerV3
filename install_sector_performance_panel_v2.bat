@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus FNO Market Watch - Sector Performance Panel V2
echo ==============================================================================
python install_sector_performance_panel_v2.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - original dashboard restored automatically.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Restart ONLY dashboard CMD:
echo   run_live_pnl_dashboard.bat
echo.
echo Do not restart scanner.
pause
