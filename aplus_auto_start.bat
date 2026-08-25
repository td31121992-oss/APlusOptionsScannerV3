@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not exist "data\logs" mkdir "data\logs"
set "LOG=data\logs\aplus_auto_start.log"
set "SCANNERLOG=data\logs\aplus_scanner_console.log"
set "DASHLOG=data\logs\aplus_dashboard_console.log"

echo.>>"%LOG%"
echo ============================================================>>"%LOG%"
echo [%date% %time%] APlus guarded morning startup>>"%LOG%"

rem CAlphaTrader starts at 09:13. APlus waits until its shared Dhan token
rem passes APlus's own preflight/profile validation. Retry up to 5 minutes.
set /a TRY=0
set /a MAXTRY=10

:WAIT_TOKEN
set /a TRY+=1
echo [%date% %time%] Dhan readiness check !TRY!/!MAXTRY!...>>"%LOG%"

if exist "aplus_preflight_check.py" (
    python aplus_preflight_check.py > "data\logs\aplus_preflight_autostart.log" 2>&1
    if not errorlevel 1 goto TOKEN_READY
) else (
    rem Fallback: import config; its shared-token resolver validates Dhan profile.
    python -c "from config import CONFIG; print('APlus config/token validation PASS')" > "data\logs\aplus_preflight_autostart.log" 2>&1
    if not errorlevel 1 goto TOKEN_READY
)

echo [%date% %time%] Shared Dhan token not ready yet. Waiting 30 seconds...>>"%LOG%"
if !TRY! GEQ !MAXTRY! goto TOKEN_FAILED
timeout /t 30 /nobreak >nul
goto WAIT_TOKEN

:TOKEN_FAILED
echo [%date% %time%] ERROR: Dhan token did not become valid within retry window. Scanner NOT started.>>"%LOG%"
echo [%date% %time%] See data\logs\aplus_preflight_autostart.log>>"%LOG%"
exit /b 10

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

rem Give it time to initialize and make sure it stayed alive.
timeout /t 25 /nobreak >nul
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -and $_.CommandLine -match 'main\.py' -and $_.CommandLine -match '--intraday-movement' }; if($p){exit 0}else{exit 1}"
if errorlevel 1 (
    echo [%date% %time%] ERROR: scanner did not remain running after launch.>>"%LOG%"
    echo [%date% %time%] See %SCANNERLOG%>>"%LOG%"
    exit /b 12
)
echo [%date% %time%] PASS: scanner is running.>>"%LOG%"

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
echo [%date% %time%] PASS: guarded morning startup completed.>>"%LOG%"
exit /b 0
