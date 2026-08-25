@echo off
setlocal
cd /d "%~dp0"
echo ====================================================================================================
echo APlus PAPER Safety + Evidence V1 - ONE GO
echo Git baseline + paper-native circuit breaker state + 100%% trade evidence capsules
echo NO LIVE ORDER ENABLEMENT
 echo ====================================================================================================
python install_aplus_safety_evidence_v1.py
if errorlevel 1 (
  echo FAILED
  pause
  exit /b 1
)
echo.
echo Verify agent:
powershell -NoProfile -Command "$p=@(Get-CimInstance Win32_Process ^| Where-Object {$_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'aplus_paper_safety_evidence_v1.py'}); Write-Host ('PAPER SAFETY/EVIDENCE AGENT COUNT: '+$p.Count); $p ^| Select-Object ProcessId,CommandLine"
echo.
echo IMPORTANT: Existing APlus scanner was not stopped or changed except safety_gate.py source for next safety evaluation.
pause
