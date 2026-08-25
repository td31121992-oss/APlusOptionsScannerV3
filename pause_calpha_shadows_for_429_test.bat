@echo off
setlocal
title Temporary CAlpha Shadow Pause - Dhan 429 Test

echo ============================================================
echo TEMPORARY CAlpha Shadow Pause - Dhan 429 Diagnostic
echo Leaves CAlpha main dashboard running.
echo Leaves APlus scanner running.
echo Stops ONLY phase4/42/43/44 shadow engines.
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$patterns='run_phase4_shadow.py|run_phase42_shadow.py|run_phase43_shadow.py|run_phase44_shadow.py';" ^
  "$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match $patterns };" ^
  "if($p){$p|ForEach-Object{Write-Host ('Stopping PID '+$_.ProcessId+' : '+$_.CommandLine); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}}else{Write-Host 'No matching CAlpha shadow engines found.'}"

echo.
echo Remaining relevant Python processes:
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and ($_.CommandLine -match 'CAlphaTrader|APlusOptionsScannerV3|main.py --intraday-movement') } | Select-Object ProcessId,CommandLine | Format-Table -AutoSize"

echo.
echo ============================================================
echo Diagnostic pause complete.
echo Keep this state for 5 minutes, then check APlus 429 frequency.
echo ============================================================
pause
endlocal
