@echo off
setlocal
cd /d "%~dp0"
if not exist "data\logs" mkdir "data\logs"

> "top_bottom_history_autostart.bat" (
  echo @echo off
  echo cd /d "%%~dp0"
  echo python top_bottom_from_open_history.py ^>^> "data\logs\top_bottom_from_open_history.log" 2^>^&1
)

schtasks /Create /F /TN "APlusOptionsScannerV3_TopBottomFromOpenHistory" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /TR "cmd.exe /c \"\"%CD%\top_bottom_history_autostart.bat\"\"" /RL LIMITED
if errorlevel 1 (
  echo FAIL: scheduled task creation failed.
  exit /b 1
)

echo.
echo SUCCESS: Top/Bottom From Open history auto-starts Mon-Fri at 09:15.
schtasks /Query /TN "APlusOptionsScannerV3_TopBottomFromOpenHistory" /V /FO LIST
