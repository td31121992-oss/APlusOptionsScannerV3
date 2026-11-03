@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" exit /b 1
"%PYTHON%" "%~dp0market_event_intelligence.py"
exit /b %ERRORLEVEL%