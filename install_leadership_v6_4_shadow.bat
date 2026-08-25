@echo off
setlocal
cd /d "%~dp0"
echo ====================================================================================================================
echo APlus Leadership V6.4 SHADOW - One Go Verify
echo RESEARCH ONLY - ZERO DHAN CALLS - ZERO PRODUCTION CHANGES
echo ====================================================================================================================
python -m py_compile leadership_v6_4_shadow.py run_leadership_v6_4_shadow.py leadership_v6_4_replay_forensic.py verify_leadership_v6_4_shadow.py
if errorlevel 1 goto :fail
python verify_leadership_v6_4_shadow.py
if errorlevel 1 goto :fail
echo.
echo SUCCESS
echo Run live shadow: run_leadership_v6_4_shadow.bat
echo Run 24-Aug forensic: run_leadership_v6_4_replay_24aug.bat
echo.
echo IMPORTANT: normal options scanner stays unchanged and can keep running.
pause
exit /b 0
:fail
echo FAILED - check error above.
pause
exit /b 1
