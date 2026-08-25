@echo off
setlocal
cd /d "%~dp0"
title Install APlus Dashboard V2
echo ====================================================================================================================
echo APlus Dashboard V2 - ONE GO
echo STANDALONE - EXISTING DASHBOARD + SCANNER UNTOUCHED
echo ====================================================================================================================
echo [1/4] Verify Python source...
python -m py_compile aplus_dashboard_v2.py install_aplus_dashboard_v2.py
if errorlevel 1 goto :fail
echo [2/4] Install runner...
python install_aplus_dashboard_v2.py
if errorlevel 1 goto :fail
echo [3/4] Stop old Dashboard V2 copy only, if any...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'aplus_dashboard_v2\.py' }); $p|ForEach-Object{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
timeout /t 2 /nobreak >nul
echo [4/4] Start Dashboard V2...
start "APlus Dashboard V2" /D "%~dp0" python aplus_dashboard_v2.py
timeout /t 3 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'aplus_dashboard_v2\.py' }); Write-Host ('DASHBOARD V2 COUNT: '+$p.Count); $p|Select-Object ProcessId,CommandLine|Format-Table -AutoSize; if($p.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail
echo.
echo ====================================================================================================================
echo SUCCESS
echo Existing dashboard remains: http://127.0.0.1:8765
echo NEW APlus Dashboard V2:     http://127.0.0.1:8772
echo ====================================================================================================================
pause
exit /b 0
:fail
echo FAILED - existing dashboard and scanner were not modified.
pause
exit /b 1
