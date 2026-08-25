@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================================================================================
echo APlus Winner-vs-Loser DNA V1
echo READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES - NO FUTURE LEAKAGE
echo ==========================================================================================================================
python -m py_compile aplus_winner_loser_dna_v1.py verify_aplus_winner_loser_dna_v1.py
if errorlevel 1 goto :fail
python verify_aplus_winner_loser_dna_v1.py
if errorlevel 1 goto :fail
echo.
python aplus_winner_loser_dna_v1.py
if errorlevel 1 goto :fail
echo.
echo COMPLETE
echo Open:
echo   data\reports\winner_loser_dna_v1\winner_loser_dna.html
pause
exit /b 0
:fail
echo FAILED - check error above.
pause
exit /b 1
