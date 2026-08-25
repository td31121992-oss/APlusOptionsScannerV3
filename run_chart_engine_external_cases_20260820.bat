@echo off
setlocal
cd /d "%~dp0"
echo Example: run another symbol set
echo.
echo Edit symbols in this BAT if you want to compare controls.
python chart_engine_forensic_replay.py --day 2026-08-20 --symbols "COFORGE,DELHIVERY,MCX,GLENMARK,SBICARD,PREMIERENE,MOTILALOFS"
pause
