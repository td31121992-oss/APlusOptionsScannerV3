@echo off
setlocal
cd /d "%~dp0"
title APlus Scanner Reliability V2 Restart
echo ====================================================================================================================
echo APlus SAFE SINGLE-INSTANCE RESTART - Reliability V2
echo ====================================================================================================================
echo [1/4] Stop all APlus intraday scanner copies...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); $p|ForEach-Object{Write-Host ('Stopping PID '+$_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
timeout /t 3 /nobreak >nul
echo [2/4] Compile...
python -m py_compile core\dhan_client.py opening_momentum_scanner.py
if errorlevel 1 goto :fail
echo [3/4] Start exactly one scanner...
start "APlus Intraday PAPER Scanner" /D "%~dp0" python main.py --intraday-movement
timeout /t 8 /nobreak >nul
echo [4/4] Verify...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); Write-Host ('SCANNER COUNT: '+$p.Count); $p|Select-Object ProcessId,CommandLine|Format-Table -AutoSize; if($p.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail
echo SUCCESS: exactly one APlus scanner is running.
exit /b 0
:fail
echo FAILED - check error above.
exit /b 1
