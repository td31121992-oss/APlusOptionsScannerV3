@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus A+ Selective PAPER Patch
echo ============================================================
python install_aplus_selective_patch.py
if errorlevel 1 (
 echo INSTALL FAILED - originals restored automatically.
 pause
 exit /b 1
)
python aplus_selective_patch_selftest.py
if errorlevel 1 (
 echo SELF-TEST FAILED - do not start scanner.
 pause
 exit /b 1
)
echo.
echo SUCCESS. Restart with run_intraday_movement.bat
pause
