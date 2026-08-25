@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo APlus Continuous Intraday F^&O Movement Scanner

echo Legacy launcher name retained for compatibility.
echo Monitoring now continues from 09:15 through 15:30 IST.
echo PAPER SIGNALS ONLY - NO LIVE ORDERS
echo ============================================================
echo.
python main.py --intraday-movement

echo.
echo Scanner exited with code %ERRORLEVEL%.
pause
endlocal
