@echo off
setlocal
cd /d "%~dp0"
title APlus Dashboard V2
echo ========================================================================================
echo APlus Dashboard V2 - Standalone
echo Existing dashboard: http://127.0.0.1:8765
echo Dashboard V2:       http://127.0.0.1:8772
echo ========================================================================================
python aplus_dashboard_v2.py
pause
