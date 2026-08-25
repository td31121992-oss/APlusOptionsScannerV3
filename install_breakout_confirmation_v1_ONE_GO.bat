@echo off
setlocal
cd /d "%~dp0"
title APlus Breakout Confirmation V1 - ONE GO
echo ==========================================================================================================================
echo APlus Breakout Confirmation V1
echo ONE GO - CONFIRMED BREAKOUTS + FUTURE BACKTEST EVIDENCE
echo PAPER SCANNER - NO LIVE ORDER ENABLEMENT
echo ==========================================================================================================================
echo [1/7] Install...
python install_breakout_confirmation_v1.py
if errorlevel 1 goto :fail
echo [2/7] Compile...
python -m py_compile intraday_movement_engine.py breakout_confirmation_v1_self_test.py breakout_evidence_collector.py audit_breakout_confirmation_v1.py
if errorlevel 1 goto :fail
echo [3/7] Self-test...
python breakout_confirmation_v1_self_test.py
if errorlevel 1 goto :fail
echo [4/7] Source audit...
python audit_breakout_confirmation_v1.py
if errorlevel 1 goto :fail
echo [5/7] Restart exactly one APlus scanner...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); $p|ForEach-Object{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
timeout /t 3 /nobreak >nul
start "APlus Intraday PAPER Scanner - Confirmed Breakouts" /D "%~dp0" python main.py --intraday-movement
timeout /t 8 /nobreak >nul
echo [6/7] Start one local evidence collector...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'breakout_evidence_collector\.py' }); $p|ForEach-Object{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
start "APlus Breakout Evidence Collector" /D "%~dp0" python breakout_evidence_collector.py
timeout /t 3 /nobreak >nul
echo [7/7] Verify...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }); $e=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'breakout_evidence_collector\.py' }); Write-Host ('SCANNER COUNT: '+$s.Count); Write-Host ('EVIDENCE COLLECTOR COUNT: '+$e.Count); if($s.Count -ne 1 -or $e.Count -ne 1){exit 2}"
if errorlevel 1 goto :fail
echo.
echo ==========================================================================================================================
echo SUCCESS
echo touch/wick = NOT CONFIRMED
echo close beyond buffer + live hold = REQUIRED
echo Future evidence: data\breakout_evidence\YYYY-MM-DD\market_watch_1m_ohlcv.csv
echo ==========================================================================================================================
pause
exit /b 0
:fail
echo FAILED - check output above.
pause
exit /b 1
