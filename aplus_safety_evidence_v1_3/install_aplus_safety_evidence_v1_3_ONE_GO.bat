@echo off
setlocal EnableExtensions
title APlus PAPER Safety + Evidence V1.3

set "PKG_DIR=%~dp0"
for %%I in ("%PKG_DIR%..") do set "PARENT_DIR=%%~fI"
if exist "%PARENT_DIR%\safety_gate.py" (set "PROJECT_ROOT=%PARENT_DIR%" & goto :ok)
if exist "%PKG_DIR%safety_gate.py" (set "PROJECT_ROOT=%PKG_DIR%" & goto :ok)
echo FAIL: project root not found.
pause
exit /b 1

:ok
cd /d "%PROJECT_ROOT%"
echo ====================================================================================================
echo APlus PAPER Safety + Evidence V1.3 - CAPSULE FIX
echo ====================================================================================================
echo PROJECT ROOT: %CD%

echo [1/5] Install corrected agent...
copy /Y "%PKG_DIR%paper_safety_evidence_agent.py" "paper_safety_evidence_agent.py" >nul
copy /Y "%PKG_DIR%verify_paper_safety_evidence_v1_3.py" "verify_paper_safety_evidence_v1_3.py" >nul
python verify_paper_safety_evidence_v1_3.py
if errorlevel 1 goto :fail

echo [2/5] Restart exactly one agent...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'paper_safety_evidence_agent\.py' }); $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
start "APlus PAPER Safety Evidence V1.3" /D "%PROJECT_ROOT%" python paper_safety_evidence_agent.py
timeout /t 7 /nobreak >nul

echo [3/5] Show state...
type data\portfolio_state.json

echo.
echo [4/5] Show evidence status...
if exist "data\reports\paper_safety_evidence_status.json" (
    type data\reports\paper_safety_evidence_status.json
) else (
    echo FAIL: status JSON not created.
    goto :fail
)

echo.
echo [5/5] Count today's capsules...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=Join-Path 'data\trade_evidence_capsules' (Get-Date -Format 'yyyy-MM-dd'); if(Test-Path $d){$n=@(Get-ChildItem $d -Filter '*.json').Count; Write-Host ('TODAY CAPSULE COUNT: '+$n); Get-ChildItem $d -Filter '*.json' | Select-Object -First 5 Name}else{Write-Host 'TODAY CAPSULE COUNT: 0'; exit 2}"
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo SUCCESS
echo V1.3 fixes missing capsules by generating stable synthetic IDs when necessary.
echo ====================================================================================================
pause
exit /b 0
:fail
echo FAILED - check output above.
pause
exit /b 1
