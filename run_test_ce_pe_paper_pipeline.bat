@echo off
setlocal
cd /d "%~dp0"
echo ================================================================================================================
echo APlus CE + PE Paper Pipeline Smoke Test
echo ISOLATED SELFTEST - NO DHAN CALLS - NO LIVE ORDERS
echo ================================================================================================================
python test_ce_pe_paper_pipeline.py
pause
