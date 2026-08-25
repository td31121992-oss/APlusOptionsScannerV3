@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Main Dashboard Navigation Bar V2
echo ==============================================================================
python install_main_dashboard_navbar_v2.py
if errorlevel 1 (
 echo.
 echo INSTALL FAILED - original restored automatically.
 pause
 exit /b 1
)
echo.
echo SUCCESS.
echo IMPORTANT: the currently running dashboard still has the old page in memory.
echo Stop ONLY the dashboard CMD with Ctrl+C, then run:
echo   run_live_pnl_dashboard.bat
echo.
echo Then open:
echo   http://127.0.0.1:8765
pause
