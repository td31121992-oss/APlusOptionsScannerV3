@echo off
cd /d "%~dp0"
echo ============================================================
echo APlus Dashboard V5 - Date + Dynamic Summary
echo ============================================================
python install_dashboard_dynamic_summary_v5.py
if errorlevel 1 (echo.&echo INSTALL FAILED - original restored.&pause&exit /b 1)
echo.
echo SUCCESS.
echo Close dashboard CMD and browser tab, then run:
echo run_live_pnl_dashboard.bat
pause
