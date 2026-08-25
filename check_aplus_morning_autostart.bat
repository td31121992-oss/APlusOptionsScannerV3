@echo off
setlocal
echo ============================================================
echo APlus Morning Automation Status
echo ============================================================
schtasks /Query /TN "APlusOptionsScannerV3_MorningStart" /FO LIST /V
echo.
echo Latest launcher log:
if exist "data\logs\aplus_auto_start.log" (
  powershell -NoProfile -Command "Get-Content 'data\logs\aplus_auto_start.log' -Tail 30"
) else (
  echo No launcher log yet. It will be created on first automatic run.
)
pause
