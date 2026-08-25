@echo off
setlocal
cd /d "%~dp0"
title APlus PAPER Circuit Breaker Wiring V1
echo ========================================================================================================================
echo APlus PAPER Circuit Breaker Wiring V1 - ONE GO
echo ZERO NEW DHAN CALLS - NO LIVE ORDER ENABLEMENT - NO ENTRY STRATEGY CHANGE
echo ========================================================================================================================
echo [1/7] Install...
python install_paper_circuit_breaker_wiring_v1.py
if errorlevel 1 goto :fail
echo [2/7] Compile...
python -m py_compile opening_momentum_scanner.py safety_gate.py paper_circuit_breaker_wiring_v1_self_test.py audit_paper_circuit_breaker_wiring_v1.py
if errorlevel 1 goto :fail
echo [3/7] Self-test...
python paper_circuit_breaker_wiring_v1_self_test.py
if errorlevel 1 goto :fail
echo [4/7] Audit...
python audit_paper_circuit_breaker_wiring_v1.py
if errorlevel 1 goto :fail
echo [5/7] Verify state...
if not exist "data\portfolio_state.json" goto :fail
type data\portfolio_state.json
echo [6/7] Restart exactly one scanner...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 3 /nobreak >nul
start "APlus PAPER Scanner - Circuit Breaker V1" /D "%~dp0" python main.py --intraday-movement
timeout /t 10 /nobreak >nul
echo [7/7] Verify scanner...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); Write-Host ('SCANNER COUNT: '+$p.Count); if($p.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail
timeout /t 65 /nobreak >nul
powershell -NoProfile -Command "Select-String -Path 'logs\scanner.log' -Pattern 'PAPER_SAFETY_BLOCK|safety_blocked=' | Select-Object -Last 30"
echo ========================================================================================================================
echo INSTALL COMPLETE
echo ========================================================================================================================
pause
exit /b 0
:fail
echo FAILED - check output above.
pause
exit /b 1
