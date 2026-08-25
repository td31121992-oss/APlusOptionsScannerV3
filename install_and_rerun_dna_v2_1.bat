@echo off
setlocal
cd /d "%~dp0"
echo ========================================================================================================
echo APlus Winner-vs-Loser DNA V2.1 - Datetime Normalization Fix
echo Fixes offset-aware vs offset-naive timestamp comparison only
echo ZERO DHAN CALLS - ZERO STRATEGY CHANGES
echo ========================================================================================================
python install_dna_v2_1_timezone_fix.py
if errorlevel 1 goto :fail
echo.
echo Now rerunning DNA V2...
call run_winner_loser_dna_v2.bat
exit /b %errorlevel%
:fail
echo FAILED - check error above.
pause
exit /b 1
