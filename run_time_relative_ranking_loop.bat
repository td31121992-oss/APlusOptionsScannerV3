@echo off
setlocal
cd /d "%~dp0"
echo ============================================================================================
echo APlus Time-Relative Ranking Research Loop
echo Reads existing fno_market_watch_latest.json every 60 seconds - ZERO Dhan API calls
echo ============================================================================================
:loop
python time_relative_ranking_engine.py
timeout /t 60 /nobreak >nul
goto loop
