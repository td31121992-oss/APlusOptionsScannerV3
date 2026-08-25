@echo off
setlocal
cd /d "%~dp0"
echo ================================================================================================================
echo APlus Conversion Blocker Forensic + Audit Logging
echo ================================================================================================================
python forensic_conversion_blocker_20260821.py
if errorlevel 1 (
 echo FORENSIC FAILED.
 pause
 exit /b 1
)
echo.
python install_conversion_audit_logging.py
if errorlevel 1 (
 echo AUDIT INSTALL FAILED.
 pause
 exit /b 2
)
echo.
echo COMPLETE.
echo No strategy, risk, or safety threshold was relaxed.
echo On the next scanner run, logs will show PASS/FAIL for each candidate reaching option-plan conversion.
pause
