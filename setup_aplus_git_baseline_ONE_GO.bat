@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_aplus_git_baseline.ps1" -ProjectRoot "%CD%"
pause
