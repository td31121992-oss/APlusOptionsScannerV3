@echo off
setlocal
title APlus Scanner Restart

cd /d "%~dp0"

echo ============================================================
echo APlusOptionsScannerV3 - Automatic Scanner Restart
echo PAPER SCANNER ONLY
echo ============================================================
echo.

echo [1/3] Stopping existing APlus intraday scanner...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'APlusOptionsScannerV3' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }; if ($procs) { $procs | ForEach-Object { Write-Host ('Stopping PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } else { Write-Host 'No existing APlus scanner found.' }"

timeout /t 3 /nobreak >nul

echo.
echo [2/3] Starting APlus intraday scanner...
start "APlus Intraday PAPER Scanner" cmd /k "cd /d ""%~dp0"" && python main.py --intraday-movement"

timeout /t 5 /nobreak >nul

echo.
echo [3/3] Verifying scanner process...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'APlusOptionsScannerV3' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' }; if ($procs) { Write-Host 'SUCCESS: APlus scanner is running.' -ForegroundColor Green; $procs | Select-Object ProcessId,CommandLine | Format-Table -AutoSize } else { Write-Host 'FAILED: Scanner process was not detected.' -ForegroundColor Red; exit 1 }"

echo.
echo ============================================================
echo Restart procedure complete.
echo CAlphaTrader processes are NOT targeted by this file.
echo ============================================================
echo.
pause
endlocal
