@echo off
setlocal
cd /d "%~dp0"
echo ======================================================================================================================
echo APlus Pending Work - One Go V4
echo EXACT-CURRENT-SOURCE INSTALLER - PAPER ONLY - NO LIVE ORDERS
echo ======================================================================================================================
echo [1/5] Install permanent paper-trade history + dashboard V4...
python install_paper_trade_history_dashboard_v4.py
if errorlevel 1 goto :fail

echo [2/5] Recover historical trades preserved in current files/backups...
python rebuild_paper_trade_history.py
if errorlevel 1 goto :fail

echo [3/5] Install Leadership V6 live SHADOW observer...
python install_leadership_v6_shadow.py
if errorlevel 1 goto :fail

echo [4/5] Run V6.3 exit optimization...
python leadership_engine_v6_3_exit_optimizer.py
if errorlevel 1 (
  echo WARNING: V6.3 research could not run; installation can still continue.
)

echo [5/5] Verify everything...
python verify_all_pending_aplus_work_v4.py
if errorlevel 1 goto :fail

echo.
echo ======================================================================================================================
echo COMPLETE
echo Open Paper History directly at:
echo   http://127.0.0.1:8765/paper-history
echo Restart dashboard only to load the new route.
echo Monday scanner: conversion audit + Leadership V6 SHADOW will log automatically.
echo Production Leadership promotion remains guarded until first live conversion-audit evidence.
echo ======================================================================================================================
pause
exit /b 0

:fail
echo.
echo FAILED - check error above.
pause
exit /b 1
