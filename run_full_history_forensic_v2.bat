@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================================================================================
echo APlus Full-History Forensic V2.1 - STOCK CALL vs OPTION OUTCOME
echo READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES
echo ==========================================================================================================================
python -m py_compile aplus_full_history_forensic_v2.py verify_aplus_full_history_forensic_v2.py
if errorlevel 1 goto :fail
python verify_aplus_full_history_forensic_v2.py
if errorlevel 1 goto :fail
echo.
python aplus_full_history_forensic_v2.py
if errorlevel 1 goto :fail
echo.
echo COMPLETE
echo Open:
echo   data\reports\full_history_forensic_v2\stock_vs_option_forensic.html
pause
exit /b 0
:fail
echo FAILED - check error above.
pause
exit /b 1
