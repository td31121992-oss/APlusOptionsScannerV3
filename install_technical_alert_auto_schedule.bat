@echo off
setlocal
cd /d "%~dp0"
if not exist "data\logs" mkdir "data\logs"
> "technical_alert_autostart.bat" (
 echo @echo off
 echo cd /d "%%~dp0"
 echo python technical_alert_engine.py ^>^> "data\logs\technical_alert_engine.log" 2^>^&1
)
> "technical_alert_dashboard_autostart.bat" (
 echo @echo off
 echo cd /d "%%~dp0"
 echo python technical_alert_dashboard.py ^>^> "data\logs\technical_alert_dashboard.log" 2^>^&1
)
schtasks /Create /F /TN "APlusOptionsScannerV3_TechnicalAlerts" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /TR "cmd.exe /c \"\"%CD%\technical_alert_autostart.bat\"\"" /RL LIMITED
if errorlevel 1 exit /b 1
schtasks /Create /F /TN "APlusOptionsScannerV3_TechnicalAlertDashboard" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /TR "cmd.exe /c \"\"%CD%\technical_alert_dashboard_autostart.bat\"\"" /RL LIMITED
if errorlevel 1 exit /b 1
echo.
echo SUCCESS: Technical alerts and dashboard auto-start Mon-Fri 09:15.
schtasks /Query /TN "APlusOptionsScannerV3_TechnicalAlerts" /V /FO LIST
