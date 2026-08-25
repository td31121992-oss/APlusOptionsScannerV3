@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus Quality-First + Unlimited Runner PAPER Patch - V2
echo ============================================================
python install_quality_first_runner_patch_v2.py
if errorlevel 1 (
 echo.
 echo INSTALL FAILED - originals restored automatically.
 pause
 exit /b 1
)
echo.
echo SUCCESS.
pause
