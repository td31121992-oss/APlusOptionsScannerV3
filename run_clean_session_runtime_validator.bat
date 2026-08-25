@echo off
cd /d "%~dp0"
python validate_clean_session_runtime.py --watch --interval 60
pause
