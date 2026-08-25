@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Candle + Chart Strategy Backtest - READ ONLY
echo NO INSTALLATION - NO PRODUCTION PATCHES - NO LIVE ORDERS
echo ==============================================================================
python backtest_candle_chart_strategy.py --project-root .
pause
