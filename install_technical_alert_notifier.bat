@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo Install APlus Technical Alert Sound + Desktop Notification
echo ==============================================================================
python install_technical_alert_notifier.py
if errorlevel 1 (
  echo INSTALL FAILED.
  pause
  exit /b 1
)
call install_technical_alert_notifier_auto_schedule.bat
if errorlevel 1 (
  echo SCHEDULER INSTALL FAILED.
  pause
  exit /b 1
)
echo.
echo COMPLETE.
echo The notifier will start automatically every weekday at 09:15.
echo.
echo To test sound immediately without waiting for tomorrow:
echo   run_technical_alert_notifier.bat
echo Note: existing alerts are baselined, so sound plays only for NEW alerts.
pause
