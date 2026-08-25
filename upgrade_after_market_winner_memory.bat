@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo Upgrade APlus After-Market Task with Automatic Winner Memory
echo ============================================================
echo Existing 15:40 scheduled task will keep using the same filename.
echo No new scheduled task is required.
echo.

if not exist "aplus_after_market_packager.py" (
  echo FAIL: existing aplus_after_market_packager.py not found.
  pause
  exit /b 1
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set STAMP=%%i
copy /Y "aplus_after_market_packager.py" "aplus_after_market_packager_before_winner_memory_%STAMP%.py" >nul

if not exist "aplus_after_market_packager_WINNER_MEMORY.py" (
  echo FAIL: aplus_after_market_packager_WINNER_MEMORY.py not found.
  pause
  exit /b 1
)

copy /Y "aplus_after_market_packager_WINNER_MEMORY.py" "aplus_after_market_packager.py" >nul
python -m py_compile aplus_after_market_packager.py
if errorlevel 1 (
  echo FAIL: compile failed. Restoring backup.
  copy /Y "aplus_after_market_packager_before_winner_memory_%STAMP%.py" "aplus_after_market_packager.py" >nul
  pause
  exit /b 1
)

echo PASS: upgraded packager compiled.
echo.
echo Running test now...
python aplus_after_market_packager.py
if errorlevel 1 (
  echo FAIL: test run failed. Restoring backup.
  copy /Y "aplus_after_market_packager_before_winner_memory_%STAMP%.py" "aplus_after_market_packager.py" >nul
  pause
  exit /b 1
)

echo.
echo ============================================================
echo SUCCESS: AUTOMATIC WINNER MEMORY ENABLED
echo ============================================================
echo Every weekday at 15:40 the existing task will now:
echo   1. build the daily winner library
echo   2. rebuild the monthly winner master
echo   3. include both in APlus_AfterMarket_LATEST.zip
echo.
pause
