@echo off
setlocal
cd /d "%~dp0"
title APlus Dhan 429 Reliability V3 - ONE GO
echo ==========================================================================================================================
echo APlus Dhan 429 Reliability V3 - SHARED MARKET QUOTE SCHEDULER
echo ONE GO - API RELIABILITY ONLY
echo ==========================================================================================================================
echo [1/5] Install V3...
python install_aplus_shared_quote_scheduler_v3.py
if errorlevel 1 goto :fail
echo [2/5] Verify...
python verify_aplus_shared_quote_scheduler_v3.py
if errorlevel 1 goto :fail
echo [3/5] Restart exactly one scanner...
call restart_aplus_scanner_v3.bat
if errorlevel 1 goto :fail
echo [4/5] Wait for first cycle...
timeout /t 80 /nobreak
echo [5/5] Show current evidence...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); Write-Host ('SCANNER COUNT: '+$p.Count); Get-Content 'logs\scanner.log' -Tail 70 | Select-String -Pattern 'Intraday movement cycle|APLUS_SHARED_QUOTE_SCHEDULER|APLUS_429_CYCLE_SKIPPED|429 Client Error|OPEN_MOVE_PATTERN_OBSERVER'"
echo.
echo ==========================================================================================================================
echo COMPLETE
echo Keep CAlphaTrader paused for a clean 5-minute validation.
echo Then run:
echo   check_aplus_429_last5min.bat
echo ==========================================================================================================================
pause
exit /b 0
:fail
echo FAILED - installer restores scanner automatically if installation fails.
pause
exit /b 1
