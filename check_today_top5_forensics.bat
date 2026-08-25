@echo off
setlocal
cd /d "%~dp0"
python check_today_top5_forensics.py
pause
