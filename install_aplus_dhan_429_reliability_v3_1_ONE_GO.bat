@echo off
setlocal
cd /d "%~dp0"
title APlus Dhan 429 Reliability V3.1
echo ==========================================================================================================================
echo APlus Dhan 429 Reliability V3.1 - ADAPTIVE SHARED MARKET QUOTE SCHEDULER
echo ==========================================================================================================================
echo [1/5] Install...
python install_aplus_shared_quote_scheduler_v3_1.py
if errorlevel 1 goto :fail
echo [2/5] Verify...
python verify_aplus_shared_quote_scheduler_v3_1.py
if errorlevel 1 goto :fail
echo [3/5] Restart exactly one APlus scanner...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); $p|ForEach-Object{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
timeout /t 3 /nobreak >nul
start "APlus Intraday PAPER Scanner" /D "%~dp0" python main.py --intraday-movement
timeout /t 8 /nobreak >nul
echo [4/5] Verify scanner count...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); Write-Host ('SCANNER COUNT: '+$p.Count); $p|Select-Object ProcessId,CommandLine|Format-Table -AutoSize; if($p.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail
echo [5/5] Wait for first cycle...
timeout /t 80 /nobreak
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content 'logs\scanner.log' -Tail 80 | Select-String -Pattern 'Intraday movement cycle|APLUS_SHARED_QUOTE_SCHEDULER_V3_1|APLUS_429_CYCLE_SKIPPED|429 Client Error|OPEN_MOVE_PATTERN_OBSERVER'"
echo.
echo COMPLETE
echo Keep CAlphaTrader paused for 5 minutes, then run:
echo   check_aplus_429_last5min.bat
pause
exit /b 0
:fail
echo FAILED - if patch writing started, original scanner is restored automatically.
pause
exit /b 1
