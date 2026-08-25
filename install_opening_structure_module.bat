@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Opening Structure Module
echo PAPER RESEARCH ONLY - NO LIVE ORDERS
echo ==============================================================================
python install_opening_structure_module.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - original dashboard restored automatically.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Keep scanner running.
echo Restart ONLY dashboard:
echo   run_live_pnl_dashboard.bat
echo Then open:
echo   http://127.0.0.1:8765/opening-structure
pause
