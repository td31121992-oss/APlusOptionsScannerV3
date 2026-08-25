@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo Install APlus Opening Structure Step 2
echo PAPER RESEARCH ONLY - NO EXECUTION
echo ==============================================================================
python install_opening_structure_step2.py
if errorlevel 1 (
  echo INSTALL FAILED.
  pause
  exit /b 1
)
call install_opening_structure_step2_auto_schedule.bat
