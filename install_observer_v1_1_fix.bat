@echo off
setlocal
cd /d "%~dp0"
echo ====================================================================================================================
echo APlus Observer V1.1 Fix + Single-Instance Scanner Repair
echo ====================================================================================================================
if not exist open_move_pattern_observer.py (
  echo FAIL: open_move_pattern_observer.py missing from package.
  pause
  exit /b 1
)
python -m py_compile open_move_pattern_observer.py
if errorlevel 1 goto :fail
echo PASS observer V1.1 compiles.
echo.
echo Now run:
echo   restart_aplus_scanner_single_instance_v2.bat
echo.
pause
exit /b 0
:fail
echo FAILED.
pause
exit /b 1
