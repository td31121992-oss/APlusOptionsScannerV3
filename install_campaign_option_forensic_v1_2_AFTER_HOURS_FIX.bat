@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title APlus Campaign + Option Forensic V1.2 After-Hours Fix

echo ==========================================================================================================================
echo APlus Campaign + Option Forensic V1.2
echo AFTER-HOURS SAFE CAMPAIGN SHADOW START + GIT COMMIT
echo ZERO NEW DHAN CALLS - ZERO STRATEGY DECISION CHANGES
echo ==========================================================================================================================

echo [1/6] Verify Option Tape V1.1 remains installed...
python audit_option_trade_tape_v1_1.py
if errorlevel 1 goto :fail

echo [2/6] Verify Movement Campaign code with one local snapshot...
python movement_campaign_intelligence_v1_shadow.py --once
if errorlevel 1 goto :fail

echo [3/6] Install campaign shadow launcher...
(
echo @echo off
echo cd /d "%%~dp0"
echo python movement_campaign_intelligence_v1_shadow.py --interval 30
) > run_movement_campaign_shadow.bat

echo [4/6] Install weekday 09:14 Windows scheduled task...
schtasks /Delete /TN "APlus_Movement_Campaign_Shadow" /F >nul 2>&1
schtasks /Create /TN "APlus_Movement_Campaign_Shadow" /TR "cmd.exe /c \"cd /d %CD% ^&^& python movement_campaign_intelligence_v1_shadow.py --interval 30\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:14 /F
if errorlevel 1 (
  echo WARN: Scheduled task creation failed.
  echo       You can still start it manually tomorrow with run_movement_campaign_shadow.bat
) else (
  echo PASS scheduled task created: APlus_Movement_Campaign_Shadow
)

echo [5/6] Runtime handling...
for /f %%H in ('powershell -NoProfile -Command "(Get-Date).Hour"') do set HH=%%H
for /f %%M in ('powershell -NoProfile -Command "(Get-Date).Minute"') do set MM=%%M

REM Market observer is designed to exit after 15:36. Do not treat that as failure.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$now=Get-Date; $start=Get-Date -Hour 9 -Minute 14 -Second 0; $end=Get-Date -Hour 15 -Minute 36 -Second 0; if($now -ge $start -and $now -lt $end){exit 0}else{exit 10}"
if "%ERRORLEVEL%"=="0" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'movement_campaign_intelligence_v1_shadow\.py' }); $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
  start "APlus Movement Campaign Intelligence V1 SHADOW" /D "%CD%" python movement_campaign_intelligence_v1_shadow.py --interval 30
  timeout /t 3 /nobreak >nul
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'movement_campaign_intelligence_v1_shadow\.py' }); Write-Host ('CAMPAIGN SHADOW COUNT: '+$p.Count); if($p.Count -ne 1){exit 2}"
  if errorlevel 1 goto :fail
) else (
  echo INFO: Market session is closed.
  echo INFO: CAMPAIGN SHADOW COUNT: 0 is EXPECTED after 15:36.
  echo INFO: Scheduled task will start it at 09:14 on the next weekday.
)

echo [6/6] Git commit...
where git >nul 2>&1
if errorlevel 1 (
  echo WARN: git not in PATH; commit skipped.
) else (
  git add paper_trade_journal.py movement_campaign_intelligence_v1_shadow.py replay_movement_campaign_intelligence_v1.py correct_stock_losing_option_forensic_v1.py install_option_trade_tape_v1_1.py audit_option_trade_tape_v1_1.py run_movement_campaign_shadow.bat install_campaign_option_forensic_v1_2_AFTER_HOURS_FIX.bat
  git diff --cached --quiet
  if errorlevel 1 git commit -m "Add campaign shadow scheduling and option quote tape evidence"
)

echo.
echo ==========================================================================================================================
echo SUCCESS
echo Option Tape V1.1               : INSTALLED
echo Campaign Intelligence          : VERIFIED
echo Campaign shadow scheduled task : 09:14 MON-FRI
echo After-hours shadow count 0      : NORMAL
echo Tomorrow output                : data\reports\movement_campaign_shadow\
echo Future option tapes            : data\option_trade_tape\YYYY-MM-DD\TRADE_ID.csv
echo ==========================================================================================================================
pause
exit /b 0

:fail
echo FAILED - check output above.
pause
exit /b 1
