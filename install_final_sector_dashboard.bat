@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Final Sector Dashboard
echo ==============================================================================
python install_final_sector_dashboard.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - originals restored automatically.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Keep scanner running.
echo Restart ONLY dashboard with:
echo   run_live_pnl_dashboard.bat
echo Then press Ctrl+F5 in browser.
pause
