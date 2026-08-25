@echo off
cd /d "%~dp0"
python top_bottom_from_open_history.py >> "data\logs\top_bottom_from_open_history.log" 2>&1
