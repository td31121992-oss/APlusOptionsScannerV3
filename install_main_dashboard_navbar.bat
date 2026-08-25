@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Main Dashboard Navigation Bar Fix
echo ==============================================================================
python install_main_dashboard_navbar.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - original dashboard restored automatically.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Restart ONLY the main dashboard:
echo   run_live_pnl_dashboard.bat
echo Then refresh http://127.0.0.1:8765
pause
