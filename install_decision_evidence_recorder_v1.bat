@echo off
setlocal
cd /d "%~dp0"
echo ======================================================================================================================
echo APlus Decision Evidence Recorder V1
echo OBSERVATION ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES
echo ======================================================================================================================
python -m py_compile aplus_decision_evidence_recorder.py run_decision_evidence_recorder.py verify_decision_evidence_recorder.py
if errorlevel 1 goto :fail
python verify_decision_evidence_recorder.py
if errorlevel 1 goto :fail
echo.
echo SUCCESS
echo Start continuous recorder with:
echo   run_decision_evidence_recorder.bat
echo.
echo One-cycle test:
echo   test_decision_evidence_recorder_once.bat
echo.
echo Existing scanner and V6.4 can remain running.
pause
exit /b 0
:fail
echo FAILED - check error above.
pause
exit /b 1
