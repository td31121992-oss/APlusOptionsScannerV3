@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo Install APlus Weekday Automatic Startup
echo ============================================================
echo Scanner + Live Trading Terminal
echo Schedule: Monday-Friday at 09:14 local Windows time
echo.

if not exist "aplus_auto_start.bat" (
  echo FAIL: aplus_auto_start.bat not found in this folder.
  pause
  exit /b 1
)

schtasks /Create /TN "APlusOptionsScannerV3_MorningStart" /TR "\"%~dp0aplus_auto_start.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:14 /F
if errorlevel 1 (
  echo.
  echo INSTALL FAILED.
  echo If Windows denied permission, right-click this BAT and Run as administrator.
  pause
  exit /b 1
)

echo.
echo PASS: Scheduled task installed.
echo.
echo Task: APlusOptionsScannerV3_MorningStart
echo Time: 09:14 Monday-Friday
echo.
echo Running a NON-SCANNER validation of the task definition...
schtasks /Query /TN "APlusOptionsScannerV3_MorningStart" /FO LIST /V | findstr /I /C:"TaskName" /C:"Next Run Time" /C:"Status" /C:"Schedule Type" /C:"Start Time" /C:"Days"
echo.
echo IMPORTANT:
echo Do NOT manually run aplus_auto_start.bat now unless you actually want
echo to start the scanner and dashboard immediately.
echo.
pause
