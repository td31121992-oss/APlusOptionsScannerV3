@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo Install APlus Automatic After-Market Package Task
echo ============================================================
echo Creates a weekday task at 15:40 local Windows time.
echo PAPER reports only. No broker orders.
echo.

if not exist "aplus_after_market_packager.py" (
  echo FAIL: aplus_after_market_packager.py missing.
  pause
  exit /b 1
)

python -m py_compile aplus_after_market_packager.py
if errorlevel 1 (
  echo FAIL: Python compile failed.
  pause
  exit /b 1
)

if not exist "data\after_market" mkdir "data\after_market"

set "TASK=APlusOptionsScannerV3_AfterMarket"
set "CMD=cmd.exe /c cd /d \"%CD%\" ^&^& python \"%CD%\aplus_after_market_packager.py\""

schtasks /Create /TN "%TASK%" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:40 /TR "%CMD%" /F
if errorlevel 1 (
  echo.
  echo WARN: Task Scheduler install failed.
  echo Run this BAT once as Administrator, or use make_after_market_package.bat manually.
  pause
  exit /b 1
)

echo PASS: scheduled task installed.
echo Running test package now...
python aplus_after_market_packager.py
if errorlevel 1 (
  echo FAIL: test package failed.
  pause
  exit /b 1
)

echo.
echo SUCCESS.
echo Daily upload file:
echo data\after_market\APlus_AfterMarket_LATEST.zip
pause
