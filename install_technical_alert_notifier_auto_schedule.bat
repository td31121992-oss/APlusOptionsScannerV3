@echo off
setlocal
cd /d "%~dp0"
if not exist "run_technical_alert_notifier.bat" (
  echo FAIL: run_technical_alert_notifier.bat missing.
  exit /b 1
)
if not exist "data\logs" mkdir "data\logs"

> "technical_alert_notifier_autostart.bat" (
  echo @echo off
  echo cd /d "%%~dp0"
  echo python technical_alert_notifier.py ^>^> "data\logs\technical_alert_notifier.log" 2^>^&1
)

schtasks /Create /F /TN "APlusOptionsScannerV3_TechnicalAlertNotifier" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /TR "cmd.exe /c \"\"%CD%\technical_alert_notifier_autostart.bat\"\"" /RL LIMITED
if errorlevel 1 (
  echo FAIL: scheduled task creation failed.
  exit /b 1
)

echo.
echo SUCCESS: Technical alert sound/popups auto-start Mon-Fri at 09:15.
schtasks /Query /TN "APlusOptionsScannerV3_TechnicalAlertNotifier" /V /FO LIST
