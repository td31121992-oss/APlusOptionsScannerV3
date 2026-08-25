@echo off
cd /d "%~dp0"
python install_aplus_final_branding.py
if errorlevel 1 (echo INSTALL FAILED - original restored.&pause&exit /b 1)
echo SUCCESS. Close dashboard and run run_live_pnl_dashboard.bat
pause
