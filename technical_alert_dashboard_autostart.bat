@echo off
cd /d "%~dp0"
python technical_alert_dashboard.py >> "data\logs\technical_alert_dashboard.log" 2>&1
