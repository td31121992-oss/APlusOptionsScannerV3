@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Opening Structure Step 2 - Automatic Scheduler
echo ==============================================================================
if not exist "run_opening_structure_evidence.bat" (
  echo FAIL: run_opening_structure_evidence.bat missing.
  echo Run install_opening_structure_step2.bat first.
  pause
  exit /b 1
)
if not exist "data\logs" mkdir "data\logs"

> "opening_structure_evidence_autostart.bat" (
  echo @echo off
  echo cd /d "%%~dp0"
  echo echo [%%date%% %%time%%] Opening Structure Step2 start ^>^> "data\logs\opening_structure_step2_autostart.log"
  echo call "run_opening_structure_evidence.bat" ^>^> "data\logs\opening_structure_step2_console.log" 2^>^&1
  echo echo [%%date%% %%time%%] Opening Structure Step2 finish RC=%%errorlevel%% ^>^> "data\logs\opening_structure_step2_autostart.log"
)

schtasks /Create /F /TN "APlusOptionsScannerV3_OpeningStructureEvidence" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /TR "cmd.exe /c \"\"%CD%\opening_structure_evidence_autostart.bat\"\"" /RL LIMITED
if errorlevel 1 (
  echo FAIL: scheduled task creation failed.
  pause
  exit /b 1
)

echo.
echo SUCCESS: Opening Structure evidence will start automatically Mon-Fri at 09:15.
schtasks /Query /TN "APlusOptionsScannerV3_OpeningStructureEvidence" /V /FO LIST
pause
