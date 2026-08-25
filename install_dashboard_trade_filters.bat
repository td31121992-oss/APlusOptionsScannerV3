@echo off
cd /d "%~dp0"
python install_dashboard_trade_filters.py
if errorlevel 1 (echo INSTALL FAILED&pause&exit /b 1)
echo SUCCESS. Restart run_live_pnl_dashboard.bat
pause
