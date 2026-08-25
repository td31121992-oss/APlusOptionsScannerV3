@echo off
setlocal
cd /d "%~dp0"
title APlus Dhan 429 Reliability V2 - ONE GO
echo ==========================================================================================================================
echo APlus Dhan 429 Reliability V2 - ONE GO
echo API RELIABILITY ONLY - NO STRATEGY / RISK / OPTION RULE CHANGES
echo ==========================================================================================================================
echo [1/5] Install...
python install_aplus_dhan_429_reliability_v2.py
if errorlevel 1 goto :fail
echo [2/5] Verify...
python verify_aplus_dhan_429_reliability_v2.py
if errorlevel 1 goto :fail
echo [3/5] Restart exactly one APlus scanner...
call restart_aplus_scanner_reliability_v2.bat
if errorlevel 1 goto :fail
echo [4/5] Wait for first live cycle...
timeout /t 75 /nobreak
echo [5/5] Show live evidence...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); Write-Host ('SCANNER COUNT: '+$p.Count); Get-Content 'logs\scanner.log' -Tail 60 | Select-String -Pattern 'Intraday movement cycle|APLUS_DHAN_429_RELIABILITY|APLUS_429_CYCLE_SKIPPED|OPEN_MOVE_PATTERN_OBSERVER|429 Client Error'"
echo.
echo ==========================================================================================================================
echo COMPLETE
echo Keep CAlpha paused for one clean 5-minute validation, then run:
echo   check_aplus_429_last5min.bat
echo ==========================================================================================================================
pause
exit /b 0
:fail
echo FAILED - installer automatically restores files if patching fails.
pause
exit /b 1
