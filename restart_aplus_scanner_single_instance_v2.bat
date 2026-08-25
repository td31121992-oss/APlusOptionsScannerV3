@echo off
setlocal
cd /d "%~dp0"
title APlus Scanner - Single Instance Restart

echo ====================================================================================================================
echo APlus Scanner - SAFE SINGLE-INSTANCE RESTART V2
echo Stops ALL python main.py --intraday-movement copies, then starts exactly ONE.
echo CAlphaTrader --loop process is NOT targeted.
echo ====================================================================================================================
echo.

echo [1/5] Stopping ALL duplicate APlus intraday Python scanners...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }; if($p){$p|ForEach-Object{Write-Host ('Stopping Python PID '+$_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}}else{Write-Host 'No Python scanner process found.'}"

echo.
echo [2/5] Stopping stale APlus CMD wrappers...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^cmd(.exe)?$' -and $_.CommandLine -match 'APlusOptionsScannerV3' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }; if($p){$p|ForEach-Object{Write-Host ('Stopping CMD wrapper PID '+$_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}}"

timeout /t 4 /nobreak >nul

echo.
echo [3/5] Compiling scanner + observer...
python -m py_compile opening_momentum_scanner.py open_move_pattern_observer.py
if errorlevel 1 goto :fail

echo.
echo [4/5] Starting exactly ONE APlus intraday scanner...
start "APlus Intraday PAPER Scanner" /D "%~dp0" python main.py --intraday-movement

timeout /t 8 /nobreak >nul

echo.
echo [5/5] Verifying exact Python instance count...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); Write-Host ('APlus scanner Python instances: '+$p.Count); $p|Select-Object ProcessId,CommandLine|Format-Table -AutoSize; if($p.Count -ne 1){Write-Host 'FAILED: expected exactly ONE scanner.' -ForegroundColor Red; exit 2}else{Write-Host 'SUCCESS: exactly ONE APlus scanner is running.' -ForegroundColor Green}"
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================================
echo SUCCESS
echo Duplicate scanners removed. One APlus scanner is running.
echo This should substantially reduce duplicate Dhan requests / 429 pressure.
echo ====================================================================================================================
pause
exit /b 0

:fail
echo.
echo FAILED - check the error above.
pause
exit /b 1
