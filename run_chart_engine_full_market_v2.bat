@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Chart Engine V2 - Full Market Canonical Replay
echo READ ONLY - NO DHAN CALLS - NO PRODUCTION CHANGES
echo ==============================================================================
python chart_engine_full_market_v2.py --day 2026-08-20 --winner-threshold 2.0
pause
