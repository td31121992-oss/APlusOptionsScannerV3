@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title APlus Movement Campaign Intelligence V1.1 - Direction Persistence

echo ==========================================================================================================================
echo APlus Movement Campaign Intelligence V1.1
echo DIRECTION-PERSISTENCE FIX - SHADOW ONLY
echo ZERO NEW DHAN CALLS - ZERO PRODUCTION ENTRY/EXIT CHANGES
echo ==========================================================================================================================

echo [1/6] Compile...
python -m py_compile movement_campaign_intelligence_v1_shadow.py replay_movement_campaign_intelligence_v1_1.py movement_campaign_v1_1_self_test.py
if errorlevel 1 goto :fail

echo [2/6] Self-test direction persistence...
python movement_campaign_v1_1_self_test.py
if errorlevel 1 goto :fail

echo [3/6] Replay 2026-08-25 using matching final direction...
python replay_movement_campaign_intelligence_v1_1.py --day 2026-08-25
if errorlevel 1 goto :fail

echo [4/6] Verify local one-cycle shadow...
python movement_campaign_intelligence_v1_shadow.py --once
if errorlevel 1 goto :fail

echo [5/6] Keep existing 09:14 scheduled task compatible...
schtasks /Query /TN "APlus_Movement_Campaign_Shadow" >nul 2>&1
if errorlevel 1 (
    echo WARN: scheduled task not found. Recreating...
    schtasks /Create /TN "APlus_Movement_Campaign_Shadow" /TR "cmd.exe /c \"cd /d %CD% ^&^& python movement_campaign_intelligence_v1_shadow.py --interval 30\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:14 /F
) else (
    echo PASS existing scheduled task remains valid because shadow filename is unchanged.
)

echo [6/6] Git commit...
where git >nul 2>&1
if errorlevel 1 (
    echo WARN: git not in PATH; commit skipped.
) else (
    git add movement_campaign_intelligence_v1_shadow.py replay_movement_campaign_intelligence_v1_1.py movement_campaign_v1_1_self_test.py install_movement_campaign_v1_1_DIRECTION_PERSISTENCE.bat README_MOVEMENT_CAMPAIGN_V1_1.txt
    git diff --cached --quiet
    if errorlevel 1 git commit -m "Add direction persistence to movement campaign shadow"
)

echo.
echo ==========================================================================================================================
echo SUCCESS
echo V1.1 remains SHADOW ONLY.
echo Required before EARLY_CAMPAIGN:
echo   3 consecutive observations in the SAME direction
echo Replay only reports detection matching the stock's FINAL direction.
echo Output:
echo   data\reports\movement_campaign_replay_v1_1\2026-08-25\
echo ==========================================================================================================================
pause
exit /b 0

:fail
echo FAILED - check output above.
pause
exit /b 1
