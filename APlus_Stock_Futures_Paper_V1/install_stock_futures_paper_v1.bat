@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================================================================
echo APlus Stock Futures PAPER Research V1 - One Go Verify
echo FUTURES PAPER ONLY - LIVE STOCK OPTIONS UNTOUCHED
echo ==========================================================================================================
python -m py_compile stock_futures_paper_engine.py run_stock_futures_paper.py stock_futures_paper_dashboard.py verify_stock_futures_paper.py
if errorlevel 1 goto :fail
python verify_stock_futures_paper.py
if errorlevel 1 goto :fail
if not exist "data\stock_futures_paper" mkdir "data\stock_futures_paper"
echo.
echo SUCCESS
echo Start engine: run_stock_futures_paper.bat
echo Start dashboard: run_stock_futures_paper_dashboard.bat
echo Dashboard: http://127.0.0.1:8766
echo IMPORTANT: existing options scanner does NOT need to be stopped.
pause
exit /b 0
:fail
echo FAILED - check error above.
pause
exit /b 1
