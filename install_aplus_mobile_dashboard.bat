@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Mobile Dashboard Installer
echo ==============================================================================
python install_aplus_mobile_dashboard.py
if errorlevel 1 (
 echo.
 echo INSTALL FAILED - originals restored automatically.
 pause
 exit /b 1
)
echo.
python show_mobile_dashboard_urls.py
echo.
echo Restart ONLY the two dashboard servers:
echo   run_live_pnl_dashboard.bat
echo   run_technical_alert_dashboard.bat
echo.
echo If Windows Firewall asks, allow Python on PRIVATE networks only.
pause
