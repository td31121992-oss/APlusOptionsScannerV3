@echo off
setlocal
cd /d "%~dp0"

if not exist "data\logs" mkdir "data\logs"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "LOG=%~dp0data\logs\aplus_live_pnl_dashboard.log"

if not exist "%PYTHON%" (
    echo ERROR: project venv Python not found: %PYTHON%
    exit /b 13
)

rem Reuse a dashboard that is already serving instead of creating another launcher.
netstat -ano -p tcp | findstr /R /C:":8765 .*LISTENING" >nul
if errorlevel 1 (
    rem Keep the Python child launch, but do not keep this batch/CMD shell waiting for it.
    start "" /b "%PYTHON%" "%~dp0aplus_live_pnl_dashboard.py" >>"%LOG%" 2>&1
    if errorlevel 1 exit /b 1
)

echo ============================================================
echo APlus Live Trading Terminal
echo ============================================================
start "" "http://127.0.0.1:8765"
exit /b 0

