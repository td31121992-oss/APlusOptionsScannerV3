@echo off
setlocal
cd /d "%~dp0"
echo ================================================================================================================
echo APlus 5-Day Pipeline Comparison + Safe Bridge Repair
echo ================================================================================================================
python compare_trade_pipeline_5days.py
if errorlevel 1 (
 echo FORENSIC FAILED.
 pause
 exit /b 1
)
echo.
python install_pipeline_bridge_audit_repair.py
if errorlevel 1 (
 echo REPAIR FAILED - original restored automatically.
 pause
 exit /b 2
)
echo.
python -m py_compile opening_momentum_scanner.py paper_trade_journal.py safety_gate.py option_selector.py
if errorlevel 1 (
 echo COMPILE VERIFY FAILED.
 pause
 exit /b 3
)
echo.
echo COMPLETE.
echo Next step after reviewing this output: V6.3 exit optimization, then production leadership integration.
pause
