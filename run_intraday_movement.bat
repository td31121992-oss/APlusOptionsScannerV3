@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo ERROR: project venv Python not found: %PYTHON%
    exit /b 13
)

echo ============================================================
echo APlus Continuous Intraday F^&O Movement Scanner
echo 09:15-15:30 IST - PAPER SIGNALS ONLY - NO LIVE ORDERS
echo ============================================================
echo.
echo Using project Python:
echo %PYTHON%
echo.

"%PYTHON%" "%~dp0main.py" --intraday-movement
set "EXITCODE=%ERRORLEVEL%"

echo.
echo Scanner exited with code %EXITCODE%.
exit /b %EXITCODE%
