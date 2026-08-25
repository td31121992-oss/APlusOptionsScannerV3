@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Mobile Dashboard V2 - Safe Runtime Injection
echo ==============================================================================
python install_aplus_mobile_dashboard_v2.py
if errorlevel 1 (
 echo.
 echo INSTALL FAILED - originals restored automatically.
 pause
 exit /b 1
)
echo.
python show_mobile_dashboard_urls_v2.py
echo.
echo IMPORTANT:
echo Restart ONLY the two dashboard servers after install.
echo   run_live_pnl_dashboard.bat
echo   run_technical_alert_dashboard.bat
echo.
echo If Windows Firewall asks, allow Python on PRIVATE networks only.
pause
