@echo off
setlocal EnableExtensions
title APlus PAPER Safety + Evidence V1.1 - ONE GO

REM Resolve package dir and project root robustly.
set "PKG_DIR=%~dp0"
for %%I in ("%PKG_DIR%..") do set "PARENT_DIR=%%~fI"

REM Case 1: package extracted inside project root\aplus_safety_evidence_v1\
if exist "%PARENT_DIR%\safety_gate.py" (
    set "PROJECT_ROOT=%PARENT_DIR%"
    goto :root_ok
)

REM Case 2: package files copied directly into project root
if exist "%PKG_DIR%safety_gate.py" (
    set "PROJECT_ROOT=%PKG_DIR%"
    goto :root_ok
)

echo ====================================================================================================
echo APlus PAPER Safety + Evidence V1.1 - ONE GO
echo Git baseline + paper-native circuit breaker state + trade evidence capsules
echo NO LIVE ORDER ENABLEMENT
echo ====================================================================================================
echo FAIL: Could not locate APlusOptionsScannerV3 project root.
echo Expected safety_gate.py either:
echo   %PARENT_DIR%\safety_gate.py
echo or
echo   %PKG_DIR%safety_gate.py
pause
exit /b 1

:root_ok
cd /d "%PROJECT_ROOT%"

echo ====================================================================================================
echo APlus PAPER Safety + Evidence V1.1 - ONE GO
echo Git baseline + paper-native circuit breaker state + trade evidence capsules
echo NO LIVE ORDER ENABLEMENT
echo ====================================================================================================
echo PROJECT ROOT: %CD%
echo PACKAGE DIR : %PKG_DIR%
echo.

echo [1/6] Verifying required project files...
if not exist "safety_gate.py" goto :missing
if not exist "opening_momentum_scanner.py" goto :missing
if not exist "data" mkdir data
if not exist "data\reports" mkdir data\reports
echo PASS required files found.

echo [2/6] Initializing Git baseline safely...
where git >nul 2>&1
if errorlevel 1 (
    echo WARN: git.exe not found in PATH. Skipping Git initialization.
    echo       Safety/evidence install will continue.
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
            echo data/**/collector_state.json
            echo backup_before_*/
        )
    )
    git add .
    git diff --cached --quiet
    if errorlevel 1 (
        git -c user.name="APlus Local Baseline" -c user.email="local@aplus.invalid" commit -m "Baseline before PAPER Safety Evidence V1.1"
        if errorlevel 1 (
            echo WARN: Git commit failed, but repository initialization succeeded.
        )
    ) else (
        echo INFO: No Git changes to commit.
    )
)

echo [3/6] Installing PAPER safety/evidence agent files...
copy /Y "%PKG_DIR%paper_safety_evidence_agent.py" "paper_safety_evidence_agent.py" >nul
if errorlevel 1 goto :fail
copy /Y "%PKG_DIR%verify_paper_safety_evidence_v1_1.py" "verify_paper_safety_evidence_v1_1.py" >nul
if errorlevel 1 goto :fail

echo [4/6] Compiling and verifying...
python -m py_compile paper_safety_evidence_agent.py verify_paper_safety_evidence_v1_1.py
if errorlevel 1 goto :fail
python verify_paper_safety_evidence_v1_1.py
if errorlevel 1 goto :fail

echo [5/6] Starting exactly one PAPER safety/evidence agent...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process ^| Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'paper_safety_evidence_agent\.py' }); $p ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
start "APlus PAPER Safety Evidence Agent" /D "%PROJECT_ROOT%" python paper_safety_evidence_agent.py
timeout /t 3 /nobreak >nul

echo [6/6] Verifying agent...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process ^| Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'paper_safety_evidence_agent\.py' }); Write-Host ('SAFETY EVIDENCE AGENT COUNT: '+$p.Count); $p ^| Select-Object ProcessId,CommandLine ^| Format-Table -AutoSize; if($p.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo SUCCESS
echo PAPER safety/evidence agent is running.
echo It updates:
echo   data\portfolio_state.json
echo and writes:
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
echo FAILED - check the output above.
pause
exit /b 1
