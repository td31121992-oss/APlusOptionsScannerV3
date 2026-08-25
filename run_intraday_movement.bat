@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo APlus Continuous Intraday F^&O Movement Scanner
echo 09:15-15:30 IST - PAPER SIGNALS ONLY - NO LIVE ORDERS
echo ============================================================
echo.
echo PAPER CE/PE trades are quality-gated for the full market session.
echo There is NO 14:45/15:05 paper-trade clock cutoff.
echo Before the first completed 5-minute candle, the scanner waits for data.
echo.
echo Main reports:
echo   data\reports\intraday_movement_latest.json
echo   data\reports\intraday_entry_ready.csv
echo   data\reports\intraday_fresh_movement.csv
echo   data\reports\intraday_wait_for_pullback.csv
echo   data\reports\intraday_near_misses.csv
echo   data\reports\paper_trades.csv
echo   data\reports\paper_trades_latest.json
echo.

python main.py --intraday-movement

echo.
echo Scanner exited with code %ERRORLEVEL%.
pause
endlocal
