@echo off
setlocal
cd /d "%~dp0..\.."

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv Python was not found.
  exit /b 1
)

".venv\Scripts\python.exe" "tools\diagnostics\aplus_incident_diagnostic.py"
exit /b %ERRORLEVEL%
