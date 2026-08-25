@echo off
cd /d "%~dp0"
echo ============================================================ >> "data\logs\btst_candidate_autostart.log"
echo [%date% %time%] BTST candidate scheduled start >> "data\logs\btst_candidate_autostart.log"
call "run_btst_candidate_scanner.bat" >> "data\logs\btst_candidate_console.log" 2>&1
echo [%date% %time%] BTST candidate scheduled finish RC=%errorlevel% >> "data\logs\btst_candidate_autostart.log"
