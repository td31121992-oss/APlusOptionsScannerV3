@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "data\logs" mkdir "data\logs"
if not exist "data\options_intelligence" mkdir "data\options_intelligence"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "LOG=%~dp0data\logs\options_intelligence_runtime.log"
set "HEALTH=%~dp0data\options_intelligence\runtime_health.json"

if not exist "%PYTHON%" (
    echo [%date% %time%] ERROR: project venv Python not found: %PYTHON%>>"%LOG%"
    exit /b 13
)

echo.>>"%LOG%"
echo ============================================================>>"%LOG%"
echo [%date% %time%] APlus Options Intelligence Runtime START>>"%LOG%"
echo [%date% %time%] 09:15-15:30 IST, read-only, trading engine untouched>>"%LOG%"
echo ============================================================>>"%LOG%"

"%PYTHON%" "%~dp0options_intelligence_runtime.py" --max-symbols 30 --cycle-delay 60 --session-start 09:15 --session-end 15:30 --reconnect-delay 20 --health-file "%HEALTH%" >>"%LOG%" 2>&1
set "EXITCODE=%ERRORLEVEL%"

echo [%date% %time%] Options Intelligence Runtime exited with code %EXITCODE%.>>"%LOG%"
exit /b %EXITCODE%
