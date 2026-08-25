@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus Late-Overheat Filter Patch
echo ============================================================
python install_late_overheat_filter_patch.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - originals restored automatically.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
pause
