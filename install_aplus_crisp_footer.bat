@echo off
cd /d "%~dp0"
python install_aplus_crisp_footer.py
if errorlevel 1 (echo INSTALL FAILED - original restored.&pause&exit /b 1)
echo SUCCESS. Close dashboard CMD/browser and run run_live_pnl_dashboard.bat
pause
