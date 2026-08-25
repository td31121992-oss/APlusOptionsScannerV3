@echo off
setlocal
title Pause CAlphaTrader For APlus 429 Isolation

echo ====================================================================================================================
echo TEMPORARY CAlphaTrader PAUSE - APlus 429 Isolation Test
echo Stops Python processes whose command line contains Desktop\CAlphaTrader\
echo Does NOT stop APlusOptionsScannerV3.
echo Does NOT stop unrelated Python processes.
echo ====================================================================================================================
echo.

echo [1/2] Stopping CAlphaTrader Python processes...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match '\\Desktop\\CAlphaTrader\\' });" ^
  "Write-Host ('CAlpha processes found: '+$p.Count);" ^
  "$p | ForEach-Object { Write-Host ('Stopping PID '+$_.ProcessId+' : '+$_.CommandLine); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

timeout /t 3 /nobreak >nul

echo.
echo [2/2] Verifying APlus scanner remains running and CAlphaTrader is paused...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'main\.py\s+--intraday-movement' });" ^
  "$c=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match '\\Desktop\\CAlphaTrader\\' });" ^
  "Write-Host ('APlus scanner count: '+$a.Count);" ^
  "Write-Host ('CAlphaTrader Python count: '+$c.Count);" ^
  "$a | Select-Object ProcessId,CommandLine | Format-Table -AutoSize"

echo.
echo ====================================================================================================================
echo KEEP THIS STATE FOR 5 MINUTES.
echo Then run check_aplus_429_last5min.bat.
echo After the test, restart CAlphaTrader using your normal CAlpha start procedure.
echo ====================================================================================================================
pause
endlocal
