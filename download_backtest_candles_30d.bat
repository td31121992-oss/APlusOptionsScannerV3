@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Historical 5m Data Download for Backtest
echo READ ONLY - DOES NOT PATCH PRODUCTION
echo ==============================================================================
python download_backtest_candles.py --days 30 --sleep 1.25
pause
