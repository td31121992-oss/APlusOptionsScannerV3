@echo off
setlocal
cd /d "%~dp0"
echo ====================================================================================================================
echo APlus Open-Move Pattern Observer V1
echo IDEA Progressive + KAYNES Reversal-to-Leadership
echo OBSERVATION ONLY - ZERO NEW DHAN CALLS - NO TRADE RULE CHANGES
echo ====================================================================================================================
python install_open_move_pattern_observer_v1.py
if errorlevel 1 goto :fail
python -m py_compile opening_momentum_scanner.py open_move_pattern_observer.py
if errorlevel 1 goto :fail
echo.
echo COMPLETE
echo Restart only the APlus intraday scanner once so it loads this observer.
echo.
echo Check live detections with:
echo powershell -NoProfile -Command "Select-String -Path 'logs\scanner.log' -Pattern 'OPEN_MOVE_PATTERN_OBSERVER' ^| Select-Object -Last 40"
echo.
echo Latest:
echo data\reports\open_move_patterns_latest.json
echo.
echo Full 09:15-open path:
echo data\open_move_pattern_history\YYYY-MM-DD\open_move_patterns.csv
pause
exit /b 0
:fail
echo FAILED - current scanner is restored automatically if installation verification fails.
pause
exit /b 1
