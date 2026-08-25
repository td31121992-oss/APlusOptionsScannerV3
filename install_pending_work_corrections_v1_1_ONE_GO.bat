@echo off
cd /d "%~dp0"
echo APlus Pending Work Corrections V1.1
copy /Y validate_clean_session_runtime.py validate_clean_session_runtime.py >nul
copy /Y post_market_movement_forensic_v2_3.py post_market_movement_forensic_v2_3.py >nul
copy /Y run_post_market_movement_forensic_v2_3.bat run_post_market_movement_forensic_v2_3.bat >nul
python -m py_compile validate_clean_session_runtime.py post_market_movement_forensic_v2_3.py
if errorlevel 1 goto fail
powershell -NoProfile -ExecutionPolicy Bypass -File cleanup_git_baseline_v1_1.ps1 -ProjectRoot "%CD%"
python validate_clean_session_runtime.py
python post_market_movement_forensic_v2_3.py --day 2026-08-25
echo DONE
pause
exit /b 0
:fail
echo FAILED
pause
exit /b 1
