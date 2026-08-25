@echo off
setlocal
cd /d "%~dp0"
echo Test download: first 5 F&O stocks only
python download_backtest_candles.py --days 10 --sleep 1.25 --limit 5
pause
