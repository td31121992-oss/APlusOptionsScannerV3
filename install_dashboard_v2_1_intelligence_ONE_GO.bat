@echo off
setlocal
cd /d "%~dp0"
title APlus Dashboard V2.1 Intelligence Upgrade
echo ====================================================================================================================
echo APlus Dashboard V2.1 - RIGHT-PANEL INTELLIGENCE UPGRADE
echo DASHBOARD ONLY - ZERO DHAN CALLS - ZERO SCANNER/TRADING CHANGES
echo ====================================================================================================================

echo [1/4] Compile and verify...
python -m py_compile aplus_dashboard_v2.py verify_dashboard_v2_1_intelligence.py
if errorlevel 1 goto :fail
python verify_dashboard_v2_1_intelligence.py
if errorlevel 1 goto :fail

echo [2/4] Stop Dashboard V2 only...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'aplus_dashboard_v2\.py' }); $p|ForEach-Object{Write-Host ('Stopping V2 PID '+$_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
timeout /t 2 /nobreak >nul

echo [3/4] Start upgraded Dashboard V2.1...
start "APlus Dashboard V2.1" /D "%~dp0" python aplus_dashboard_v2.py
timeout /t 3 /nobreak >nul

echo [4/4] Verify single instance...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'aplus_dashboard_v2\.py' }); Write-Host ('DASHBOARD V2 COUNT: '+$p.Count); $p|Select-Object ProcessId,CommandLine|Format-Table -AutoSize; if($p.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================================
echo SUCCESS
echo Open / refresh:
echo   http://127.0.0.1:8772
echo.
echo TEST IDEA FIRST.
echo Its right panel should no longer show all-zero 5m/10m momentum and 50%% range position.
echo ====================================================================================================================
pause
exit /b 0

:fail
echo FAILED - scanner and trading system were not touched.
pause
exit /b 1
