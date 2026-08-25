@echo off
setlocal
cd /d "%~dp0"
echo ================================================================================================
echo APlus Scanner-Wide Atomic-Write Reliability Fix
echo REPORT FILES ONLY - NO STRATEGY / RISK / ORDER CHANGES
echo ================================================================================================
python install_scanner_atomic_write_reliability.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - scanner restored automatically.
  pause
  exit /b 1
)
echo.
python verify_scanner_atomic_write_reliability.py
if errorlevel 1 (
  echo.
  echo SELF-TEST FAILED.
  pause
  exit /b 2
)
echo.
echo COMPLETE
echo Restart run_intraday_movement.bat after this.
pause
