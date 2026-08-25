@echo off
cd /d "%~dp0"
python technical_alert_engine.py >> "data\logs\technical_alert_engine.log" 2>&1
