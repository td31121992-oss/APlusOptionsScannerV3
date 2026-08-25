@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo Install APlus BTST Research Module
echo ==============================================================================
python install_btst_research.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Today at 14:45 run:
echo   run_btst_candidate_scanner.bat
echo.
echo Tomorrow morning at 09:15 run:
echo   run_btst_next_morning_tracker.bat
pause
