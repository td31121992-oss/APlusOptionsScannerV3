@echo off
cd /d "%~dp0"
echo APlus Decision Evidence Recorder V1
echo ZERO DHAN CALLS - OBSERVATION ONLY
python run_decision_evidence_recorder.py --interval 15
pause
