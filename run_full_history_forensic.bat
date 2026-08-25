@echo off
setlocal
cd /d "%~dp0"
echo ====================================================================================================================
echo APlus Full-History Profitability + Trade Forensic V1
echo READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES
echo ====================================================================================================================
python -m py_compile aplus_full_history_forensic.py verify_aplus_full_history_forensic.py
if errorlevel 1 goto :fail
python verify_aplus_full_history_forensic.py
if errorlevel 1 goto :fail
echo.
python aplus_full_history_forensic.py
if errorlevel 1 goto :fail
echo.
echo COMPLETE
echo Open:
echo   data\reports\full_history_forensic\full_history_forensic.html
echo.
pause
exit /b 0
:fail
echo.
echo FAILED - check error above.
pause
exit /b 1
