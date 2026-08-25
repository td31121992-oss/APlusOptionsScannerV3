@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo Install APlus Real-Time Technical Alert System
echo PAPER / RESEARCH ALERTS ONLY
echo ==============================================================================
python install_technical_alert_system.py
if errorlevel 1 (
 echo INSTALL FAILED.
 pause
 exit /b 1
)
call install_technical_alert_auto_schedule.bat
if errorlevel 1 (
 echo SCHEDULER INSTALL FAILED.
 pause
 exit /b 1
)
echo.
echo COMPLETE.
echo Alert dashboard: http://127.0.0.1:8766
echo Everything will auto-start on weekdays at 09:15.
pause
