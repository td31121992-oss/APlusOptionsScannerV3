@echo off
cd /d "%~dp0"
python install_dashboard_combined_ui_v2.py
if errorlevel 1 (echo INSTALL FAILED&pause&exit /b 1)
echo SUCCESS. Close old dashboard and run run_live_pnl_dashboard.bat
pause
