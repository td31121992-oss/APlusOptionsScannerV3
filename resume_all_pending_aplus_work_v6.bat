@echo off
setlocal
cd /d "%~dp0"
echo ======================================================================================================================
echo APlus Pending Work Resume - V6
echo STARTS FROM STEP 3 - HISTORY/DASHBOARD ALREADY INSTALLED
echo PAPER ONLY - NO LIVE ORDERS
echo ======================================================================================================================

echo [3/5] Install Leadership V6 live SHADOW V2...
python install_leadership_v6_shadow_v2.py
if errorlevel 1 goto :fail

echo [4/5] Run V6.3 exit optimization...
python leadership_engine_v6_3_exit_optimizer.py
if errorlevel 1 (
  echo WARNING: V6.3 research could not run. Remaining install can still continue.
)

echo [5/5] Verify everything...
python verify_all_pending_aplus_work_v4.py
if errorlevel 1 goto :fail

echo.
echo ======================================================================================================================
echo COMPLETE
echo Paper History:
echo   http://127.0.0.1:8765/paper-history
echo.
echo Restart dashboard only if not already restarted.
echo Monday: start scanner normally; conversion audit + Leadership V6 SHADOW will log.
echo Production Leadership promotion remains guarded until first live conversion-audit evidence.
echo ======================================================================================================================
pause
exit /b 0

:fail
echo.
echo FAILED - check error above.
pause
exit /b 1
