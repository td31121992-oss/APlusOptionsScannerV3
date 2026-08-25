@echo off
cd /d "%~dp0"
echo ============================================================
echo APlus Exact Footer Installer
echo ============================================================
python install_aplus_exact_footer.py
if errorlevel 1 (echo.&echo INSTALL FAILED - original restored.&pause&exit /b 1)
echo.
echo SUCCESS.
echo Close dashboard CMD/browser tab and run:
echo run_live_pnl_dashboard.bat
pause
