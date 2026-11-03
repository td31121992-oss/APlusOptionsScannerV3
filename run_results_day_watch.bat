@echo off
rem Results-day watch (shadow): lists today's F&O results stocks and prints an ALERT line when one moves fast. Start any time from 09:10; it stops itself at 15:31.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set PY=".venv\Scripts\python.exe") else (set PY=python)
%PY% results_day_watch.py live
pause
