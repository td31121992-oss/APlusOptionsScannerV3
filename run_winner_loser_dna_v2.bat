@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================================================================
echo APlus Winner-vs-Loser DNA V2 - Reconstructed Entry Fingerprint
echo READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES - TRUE DAY HOLDOUT
echo ==============================================================================================================================
python -m py_compile aplus_winner_loser_dna_v2.py verify_aplus_winner_loser_dna_v2.py
if errorlevel 1 goto :fail
python verify_aplus_winner_loser_dna_v2.py
if errorlevel 1 goto :fail
echo.
python aplus_winner_loser_dna_v2.py
if errorlevel 1 goto :fail
echo.
echo COMPLETE
echo Open:
echo   data\reports\winner_loser_dna_v2\winner_loser_dna_v2.html
pause
exit /b 0
:fail
echo FAILED - check error above.
pause
exit /b 1
