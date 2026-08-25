@echo off
setlocal
cd /d "%~dp0"
echo ================================================================================================================
echo APlus Selective-Gate Regression Forensic
echo READ ONLY - NO STRATEGY CHANGES
echo ================================================================================================================
python compare_selective_gate_versions.py
pause
