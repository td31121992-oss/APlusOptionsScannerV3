@echo off
cd /d "%~dp0"
echo APlus Pending Work Completion V1
python -m py_compile validate_clean_session_runtime.py post_market_movement_forensic_v2_2.py
if errorlevel 1 goto fail
call setup_aplus_git_baseline_ONE_GO.bat
python validate_clean_session_runtime.py
echo.
echo TOMORROW: run_clean_session_runtime_validator.bat
echo POST MARKET: run_post_market_movement_forensic_v2_2.bat
echo DONE
pause
exit /b 0
:fail
echo FAILED
pause
exit /b 1
