@echo off
cd /d "%~dp0"
if "%1"=="" (python post_market_movement_forensic_v2_2.py) else (python post_market_movement_forensic_v2_2.py --day %1)
pause
