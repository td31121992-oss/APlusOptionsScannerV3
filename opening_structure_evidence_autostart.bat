@echo off
cd /d "%~dp0"
echo [%date% %time%] Opening Structure Step2 start >> "data\logs\opening_structure_step2_autostart.log"
call "run_opening_structure_evidence.bat" >> "data\logs\opening_structure_step2_console.log" 2>&1
echo [%date% %time%] Opening Structure Step2 finish RC=%errorlevel% >> "data\logs\opening_structure_step2_autostart.log"
