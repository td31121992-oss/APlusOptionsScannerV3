@echo off
setlocal
cd /d "%~dp0"
echo ======================================================================================================================
echo APlus Pending Work - One Go
echo PAPER ONLY - NO LIVE ORDERS
echo ======================================================================================================================
echo [1/5] Install permanent paper-trade history + dashboard...
python install_paper_trade_history_dashboard.py
if errorlevel 1 goto :fail
echo [2/5] Recover any historical trades preserved in current files/backups...
python rebuild_paper_trade_history.py
if errorlevel 1 goto :fail
echo [3/5] Install Leadership V6 live SHADOW observer...
python install_leadership_v6_shadow.py
if errorlevel 1 goto :fail
echo [4/5] Run V6.3 exit optimization...
python leadership_engine_v6_3_exit_optimizer.py
if errorlevel 1 echo WARNING: V6.3 research could not run; installation can still continue.
echo [5/5] Verify...
python verify_all_pending_aplus_work.py
if errorlevel 1 goto :fail
echo.
echo ======================================================================================================================
echo COMPLETE
echo Dashboard history: http://127.0.0.1:8765/paper-history
echo Restart ONLY dashboard now to load the new history page.
echo On Monday start scanner normally: conversion audit + Leadership V6 SHADOW will both log.
echo Production Leadership promotion is prepared but deliberately guarded until first live conversion audit.
echo ======================================================================================================================
pause
exit /b 0
:fail
echo.
echo FAILED - check error above. Installers restore modified production files automatically when their patch fails.
pause
exit /b 1
