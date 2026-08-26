@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%CD%"

echo ================================================================================================================
echo APlus FULL MARKET AUTOMATION V1.1
echo FIXES V1 SELF-COPY INSTALL FAILURE
echo Auto-start + auto-heal:
echo   PAPER safety/evidence agent
echo   main intraday scanner
echo   Dashboard V2
echo   Campaign Intelligence shadow
echo NO LIVE ORDER ENABLEMENT
echo ================================================================================================================

if not exist "%ROOT%\opening_momentum_scanner.py" (
  echo FAIL: run this from APlusOptionsScannerV3 root.
  goto fail
)

if not exist "%ROOT%\aplus_market_runtime_watchdog.ps1" (
  echo FAIL: aplus_market_runtime_watchdog.ps1 not found in project root.
  echo Re-extract the automation ZIP into APlusOptionsScannerV3 root.
  goto fail
)

echo [1/5] Remove older automation tasks if present...
schtasks /Delete /TN "APlus_Full_AutoStart" /F >nul 2>&1
schtasks /Delete /TN "APlus_Runtime_Watchdog" /F >nul 2>&1

echo [2/5] Create weekday 09:05 auto-start...
schtasks /Create /TN "APlus_Full_AutoStart" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ^"%ROOT%\aplus_market_runtime_watchdog.ps1^" -ProjectRoot ^"%ROOT%^"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:05 /F
if errorlevel 1 (
  echo FAIL: could not create APlus_Full_AutoStart scheduled task.
  goto fail
)

echo [3/5] Create 5-minute runtime watchdog...
schtasks /Create /TN "APlus_Runtime_Watchdog" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ^"%ROOT%\aplus_market_runtime_watchdog.ps1^" -ProjectRoot ^"%ROOT%^"" /SC DAILY /ST 09:10 /RI 5 /DU 06:25 /F
if errorlevel 1 (
  echo FAIL: could not create APlus_Runtime_Watchdog scheduled task.
  goto fail
)

echo [4/5] Run watchdog once now for verification...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\aplus_market_runtime_watchdog.ps1" -ProjectRoot "%ROOT%"
if errorlevel 1 (
  echo FAIL: watchdog verification failed.
  goto fail
)

echo [5/5] Show installed tasks...
schtasks /Query /TN "APlus_Full_AutoStart" /FO LIST
if errorlevel 1 goto fail
schtasks /Query /TN "APlus_Runtime_Watchdog" /FO LIST
if errorlevel 1 goto fail

where git >nul 2>&1
if not errorlevel 1 (
  git add aplus_market_runtime_watchdog.ps1 install_aplus_FULL_AUTOMATION_V1_1_ONE_GO.bat
  git diff --cached --quiet
  if errorlevel 1 git commit -m "Fix APlus full automation installer"
)

echo.
echo ================================================================================================================
echo SUCCESS
echo Weekdays:
echo   09:05  safety agent first
echo   09:10+ scanner and dashboard ensured alive
echo   09:14+ campaign shadow ensured alive when file exists
echo   every 5 minutes watchdog rechecks runtime
echo   scanner waits for TODAY portfolio_state date
echo Health: data\aplus_automation_health.json
echo ================================================================================================================
pause
exit /b 0

:fail
echo.
echo ================================================================================================================
echo FAILED - see the specific FAIL line above.
echo ================================================================================================================
pause
exit /b 1
