@echo off
setlocal
cd /d "%~dp0"
title APlus V3 Single Instance Restart
echo ====================================================================================================================
echo APlus V3 SAFE SINGLE-INSTANCE RESTART
echo ====================================================================================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); $p|ForEach-Object{Write-Host ('Stopping PID '+$_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
timeout /t 3 /nobreak >nul
python -m py_compile opening_momentum_scanner.py core\dhan_client.py
if errorlevel 1 goto :fail
start "APlus Intraday PAPER Scanner" /D "%~dp0" python main.py --intraday-movement
timeout /t 8 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); Write-Host ('SCANNER COUNT: '+$p.Count); $p|Select-Object ProcessId,CommandLine|Format-Table -AutoSize; if($p.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail
echo SUCCESS: exactly one APlus scanner is running.
exit /b 0
:fail
echo FAILED - check error above.
exit /b 1
