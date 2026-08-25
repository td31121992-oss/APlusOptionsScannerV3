@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus API Reliability Fix
echo PAPER ONLY - NO STRATEGY CHANGES - NO LIVE ORDERS
echo ==============================================================================
python install_api_reliability_fix.py
if errorlevel 1 (
 echo.
 echo INSTALL FAILED - originals restored automatically.
 pause
 exit /b 1
)
echo.
python verify_api_reliability_fix.py
echo.
echo COMPLETE.
echo Restart run_intraday_movement.bat before the next market session.
pause
