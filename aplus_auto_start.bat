@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not exist "data\logs" mkdir "data\logs"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "LOG=data\logs\aplus_auto_start.log"
if not exist "%PYTHON%" (
    echo [%date% %time%] ERROR: project venv Python not found: %PYTHON%>>"%LOG%"
    exit /b 13
)
set "SCANNERLOG=data\logs\aplus_scanner_console.log"
set "DASHLOG=data\logs\aplus_dashboard_console.log"

echo.>>"%LOG%"
echo ============================================================>>"%LOG%"
echo [%date% %time%] APlus guarded unattended startup/recovery>>"%LOG%"

rem IMPORTANT:
rem Do not give up after a short Dhan-token retry window. If the shared
rem token is temporarily unavailable at 09:14, keep retrying safely until
rem the market session ends. This preserves the existing safety rule:
rem no valid Dhan profile -> no scanner start.
set /a RETRY=0

:SESSION_CHECK
powershell -NoProfile -Command "$n=(Get-Date); if($n.DayOfWeek -eq 'Saturday' -or $n.DayOfWeek -eq 'Sunday'){exit 2}; $t=$n.TimeOfDay; if($t -lt [TimeSpan]::Parse('09:05:00')){exit 3}; if($t -gt [TimeSpan]::Parse('15:35:00')){exit 4}; exit 0"
if errorlevel 4 goto MARKET_DONE
if errorlevel 3 (
    echo [%date% %time%] Outside startup window; waiting 60 seconds.>>"%LOG%"
    timeout /t 60 /nobreak >nul
    goto SESSION_CHECK
)
if errorlevel 2 goto MARKET_DONE

set /a RETRY+=1
echo [%date% %time%] Dhan readiness attempt !RETRY!...>>"%LOG%"

if exist "aplus_preflight_check.py" (
    "%PYTHON%" aplus_preflight_check.py > "data\logs\aplus_preflight_autostart.log" 2>&1
    if not errorlevel 1 goto TOKEN_READY
) else (
    "%PYTHON%" -c "from config import CONFIG; print('APlus config/token validation PASS')" > "data\logs\aplus_preflight_autostart.log" 2>&1
    if not errorlevel 1 goto TOKEN_READY
)

echo [%date% %time%] Shared Dhan token not ready. Safe retry in 60 seconds...>>"%LOG%"
timeout /t 60 /nobreak >nul
goto SESSION_CHECK

:TOKEN_READY
echo [%date% %time%] PASS: shared Dhan token/preflight validation succeeded.>>"%LOG%"

rem Avoid duplicate scanner.
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -and $_.CommandLine -match 'main\.py' -and $_.CommandLine -match '--intraday-movement' }; if($p){exit 0}else{exit 1}"
if not errorlevel 1 (
    echo [%date% %time%] Scanner already running - duplicate skipped.>>"%LOG%"
    goto START_DASHBOARD
)

if not exist "run_intraday_movement.bat" (
    echo [%date% %time%] ERROR: run_intraday_movement.bat not found.>>"%LOG%"
    exit /b 11
)

echo [%date% %time%] Starting APlus scanner...>>"%LOG%"
start "APlus Intraday Scanner" /min cmd /c "cd /d ""%~dp0"" && call run_intraday_movement.bat >> ""%SCANNERLOG%"" 2>&1"

rem Verify startup. If the scanner exits immediately, retry safely instead of
rem abandoning the day after one failed launch.
timeout /t 25 /nobreak >nul
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -and $_.CommandLine -match 'main\.py' -and $_.CommandLine -match '--intraday-movement' }; if($p){exit 0}else{exit 1}"
if errorlevel 1 (
    echo [%date% %time%] WARNING: scanner did not remain running. Safe recovery retry in 60 seconds.>>"%LOG%"
    timeout /t 60 /nobreak >nul
    goto SESSION_CHECK
)
echo [%date% %time%] PASS: scanner is running.>>"%LOG%"
goto START_DASHBOARD

:START_DASHBOARD
rem Dashboard is independent of broker order execution, but avoid duplicates.
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -and $_.CommandLine -match 'aplus_live_pnl_dashboard\.py' }; if($p){exit 0}else{exit 1}"
if not errorlevel 1 (
    echo [%date% %time%] Dashboard already running - duplicate skipped.>>"%LOG%"
    goto DONE
)

if exist "run_live_pnl_dashboard.bat" (
    echo [%date% %time%] Starting APlus Live Trading Terminal...>>"%LOG%"
    start "APlus Live Trading Terminal" /min cmd /c "cd /d ""%~dp0"" && call run_live_pnl_dashboard.bat >> ""%DASHLOG%"" 2>&1"
) else (
    echo [%date% %time%] WARNING: run_live_pnl_dashboard.bat not found.>>"%LOG%"
)

:DONE
echo [%date% %time%] PASS: unattended startup/recovery completed.>>"%LOG%"
exit /b 0

:MARKET_DONE
echo [%date% %time%] Market/startup window ended; no scanner start attempted.>>"%LOG%"
exit /b 0
