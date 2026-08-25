@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================================================
echo APlus Atomic-Write Reliability Fix V2
echo ADAPTIVE INSTALLER - PAPER JOURNAL ONLY
echo ==========================================================================================
python install_atomic_write_reliability_fix_v2.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - original restored automatically.
  pause
  exit /b 1
)
echo.
python verify_atomic_write_reliability_fix_v2.py
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
