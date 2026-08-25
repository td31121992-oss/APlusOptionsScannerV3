@echo off
cd /d "%~dp0"
echo ============================================================
echo APlus Dashboard Identity + Date Patch
echo ============================================================
python install_dashboard_identity_v2.py
if errorlevel 1 (
 echo INSTALL FAILED - original restored automatically.
 pause
 exit /b 1
)
echo.
echo SUCCESS.
echo Close dashboard CMD/browser tab and run run_live_pnl_dashboard.bat
pause
