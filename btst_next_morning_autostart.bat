@echo off
cd /d "%~dp0"
echo ============================================================ >> "data\logs\btst_next_morning_autostart.log"
echo [%date% %time%] BTST next-morning scheduled start >> "data\logs\btst_next_morning_autostart.log"
call "run_btst_next_morning_tracker.bat" >> "data\logs\btst_next_morning_console.log" 2>&1
echo [%date% %time%] BTST next-morning scheduled finish RC=%errorlevel% >> "data\logs\btst_next_morning_autostart.log"
