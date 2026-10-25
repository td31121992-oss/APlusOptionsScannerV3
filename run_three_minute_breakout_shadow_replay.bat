@echo off
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo ============================================================
echo APlus 3-minute breakout/breakdown SHADOW replay
echo READ ONLY - no orders, no production scanner changes
echo ============================================================
"%PY%" "%~dp0run_three_minute_breakout_shadow_replay.py" %*
set "RC=%ERRORLEVEL%"
echo.
echo Exit code: %RC%
echo Results, if retrieval succeeded:
echo   data\three_minute_shadow_replay\summary.json
echo   data\three_minute_shadow_replay\underlying_1m_ohlcv.csv
echo   data\three_minute_shadow_replay\underlying_3m_ohlcv.csv
echo   data\three_minute_shadow_replay\shadow_candidates_outcomes.csv
echo.
pause
exit /b %RC%
