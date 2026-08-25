@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Chart Engine V3 - Persistence / False Positive Test
echo READ ONLY - NO DHAN CALLS - NO PRODUCTION CHANGES
echo ==============================================================================
python chart_engine_v3_persistence_test.py --day 2026-08-20 --window 3 --min-aplus 2
pause
