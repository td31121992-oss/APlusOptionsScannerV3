@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo Install APlus Top/Bottom From Open History
echo ==============================================================================
python install_top_bottom_from_open_history.py
if errorlevel 1 (
 echo INSTALL FAILED.
 pause
 exit /b 1
)
call install_top_bottom_from_open_history_auto_schedule.bat
if errorlevel 1 (
 echo SCHEDULER INSTALL FAILED.
 pause
 exit /b 1
)
echo.
echo COMPLETE - nothing manual required from tomorrow.
pause
