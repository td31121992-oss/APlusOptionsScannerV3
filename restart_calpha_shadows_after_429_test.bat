@echo off
setlocal
title Restart CAlpha Shadow Engines

cd /d "C:\Users\Darpan.bobhate\Desktop\CAlphaTrader"

echo ============================================================
echo Restart CAlpha Phase Shadow Engines
echo Starts phase4 / phase42 / phase43 / phase44 only if not running.
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "function Start-IfMissing($pattern,$cmd,$title){" ^
  "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match $pattern });" ^
  "if($p.Count -eq 0){Write-Host ('Starting '+$title); Start-Process cmd.exe -ArgumentList '/k',('cd /d ""C:\Users\Darpan.bobhate\Desktop\CAlphaTrader"" && '+$cmd)}else{Write-Host ($title+' already running; not duplicated.')}};" ^
  "Start-IfMissing 'run_phase4_shadow.py' 'python run_phase4_shadow.py --interval 3 --stop-at 15:35' 'Phase4';" ^
  "Start-IfMissing 'run_phase42_shadow.py' 'python run_phase42_shadow.py --interval 3 --stop-at 15:35' 'Phase42';" ^
  "Start-IfMissing 'run_phase43_shadow.py' 'python run_phase43_shadow.py --interval 3 --candle-refresh 20 --stop-at 15:35' 'Phase43';" ^
  "Start-IfMissing 'run_phase44_shadow.py' 'python run_phase44_shadow.py --interval 2' 'Phase44'"

echo.
echo Current CAlpha shadow processes:
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'run_phase4_shadow.py|run_phase42_shadow.py|run_phase43_shadow.py|run_phase44_shadow.py' } | Select-Object ProcessId,CommandLine | Format-Table -AutoSize"

echo.
pause
endlocal
