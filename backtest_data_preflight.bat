@echo off
setlocal
cd /d "%~dp0"
python backtest_data_preflight.py
pause
