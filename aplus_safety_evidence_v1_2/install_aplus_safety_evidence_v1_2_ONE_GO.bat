@echo off
setlocal EnableExtensions
title APlus PAPER Safety + Evidence V1.2 - ONE GO

set "PKG_DIR=%~dp0"
for %%I in ("%PKG_DIR%..") do set "PARENT_DIR=%%~fI"

if exist "%PARENT_DIR%\safety_gate.py" (
    set "PROJECT_ROOT=%PARENT_DIR%"
    goto :root_ok
)
if exist "%PKG_DIR%safety_gate.py" (
    set "PROJECT_ROOT=%PKG_DIR%"
    goto :root_ok
)

echo FAIL: Could not locate APlusOptionsScannerV3 project root.
pause
exit /b 1

:root_ok
cd /d "%PROJECT_ROOT%"

echo ====================================================================================================
echo APlus PAPER Safety + Evidence V1.2 - ONE GO
echo Git baseline + paper-native circuit breaker state + trade evidence capsules
echo NO LIVE ORDER ENABLEMENT
echo ====================================================================================================
echo PROJECT ROOT: %CD%
echo PACKAGE DIR : %PKG_DIR%
echo.

echo [1/6] Verifying required project files...
if not exist "safety_gate.py" goto :missing
if not exist "opening_momentum_scanner.py" goto :missing
echo PASS required files found.

echo [2/6] Initializing Git baseline safely...
where git >nul 2>&1
if errorlevel 1 (
    echo WARN: git.exe not found in PATH. Skipping Git initialization.
    echo       Install Git for Windows later, then we can baseline the repo separately.
) else (
    if not exist ".git" (
        git init
        if errorlevel 1 goto :fail
    )
    if not exist ".gitignore" (
        >.gitignore (
            echo __pycache__/
            echo *.pyc
            echo .env
            echo *.log
            echo logs/
            echo data/cache/
            echo data/reports/*.tmp
            echo backup_before_*/
        )
    )
    git add .
    git diff --cached --quiet
    if errorlevel 1 (
        git -c user.name="APlus Local Baseline" -c user.email="local@aplus.invalid" commit -m "Baseline before PAPER Safety Evidence V1.2"
        if errorlevel 1 echo WARN: Git commit failed, repository remains initialized.
    ) else (
        echo INFO: No Git changes to commit.
    )
)

echo [3/6] Installing PAPER safety/evidence agent files...
copy /Y "%PKG_DIR%paper_safety_evidence_agent.py" "paper_safety_evidence_agent.py" >nul
if errorlevel 1 goto :fail
copy /Y "%PKG_DIR%verify_paper_safety_evidence_v1_2.py" "verify_paper_safety_evidence_v1_2.py" >nul
if errorlevel 1 goto :fail

echo [4/6] Compiling and verifying...
python -m py_compile paper_safety_evidence_agent.py verify_paper_safety_evidence_v1_2.py
if errorlevel 1 goto :fail
python verify_paper_safety_evidence_v1_2.py
if errorlevel 1 goto :fail

echo [5/6] Starting exactly one PAPER safety/evidence agent...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'paper_safety_evidence_agent\.py' }); $p | ForEach-Object { Write-Host ('Stopping old agent PID '+$_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
start "APlus PAPER Safety Evidence Agent" /D "%PROJECT_ROOT%" python paper_safety_evidence_agent.py
timeout /t 3 /nobreak >nul

echo [6/6] Verifying agent and generated state...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'paper_safety_evidence_agent\.py' }); Write-Host ('SAFETY EVIDENCE AGENT COUNT: '+$p.Count); $p | Select-Object ProcessId,CommandLine | Format-Table -AutoSize; if($p.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail

timeout /t 6 /nobreak >nul
if exist "data\portfolio_state.json" (
    echo PASS data\portfolio_state.json exists
    powershell -NoProfile -Command "Get-Content 'data\portfolio_state.json' -Raw"
) else (
    echo FAIL data\portfolio_state.json was not created
    goto :fail
)

echo.
echo ====================================================================================================
echo SUCCESS
echo PAPER safety/evidence agent is running.
echo Evidence capsules:
echo   data\trade_evidence_capsules\YYYY-MM-DD\TRADE_ID.json
echo.
echo Existing scanner/trading code was NOT modified by this package.
echo ====================================================================================================
pause
exit /b 0

:missing
echo FAIL: required APlus project file missing in %CD%.
goto :fail

:fail
echo FAILED - check output above.
pause
exit /b 1
