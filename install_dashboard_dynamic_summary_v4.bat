@echo off
cd /d "%~dp0"
python install_dashboard_dynamic_summary_v4.py
if errorlevel 1 (echo INSTALL FAILED&pause&exit /b 1)
echo SUCCESS. Close dashboard and run run_live_pnl_dashboard.bat
pause
