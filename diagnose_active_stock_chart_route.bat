@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Dashboard Active Route Diagnostic
echo ==============================================================================
python diagnose_active_stock_chart_route.py
echo.
echo PROCESS USING PORT 8765
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  echo PID %%P
  powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter 'ProcessId=%%P' | Select-Object ProcessId,ExecutablePath,CommandLine | Format-List"
)
pause
