@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================================================
echo APlus Atomic-Write Reliability Fix
echo PAPER JOURNAL ONLY - NO STRATEGY OR RISK CHANGES
echo ==========================================================================================
python install_atomic_write_reliability_fix.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - original restored automatically.
  pause
  exit /b 1
)
echo.
python verify_atomic_write_reliability_fix.py
if errorlevel 1 (
  echo.
  echo SELF-TEST FAILED.
  pause
  exit /b 2
)
echo.
echo ==========================================================================================
echo COMPLETE
echo ==========================================================================================
echo Restart run_intraday_movement.bat so the scanner loads the fix.
echo Dhan HTTP 429 remains a separate issue.
pause
