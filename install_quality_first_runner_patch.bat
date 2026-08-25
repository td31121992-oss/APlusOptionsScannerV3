@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus Quality-First + Unlimited Runner PAPER Patch
echo ============================================================
python install_quality_first_runner_patch.py
if errorlevel 1 (
 echo INSTALL FAILED - originals restored automatically.
 pause
 exit /b 1
)
python quality_first_runner_selftest.py
if errorlevel 1 (
 echo SELF-TEST FAILED - do not start scanner.
 pause
 exit /b 1
)
echo.
echo SUCCESS. Ready for next PAPER session.
pause
