@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo FAIL: project venv Python not found.
  exit /b 2
)

echo ============================================================
echo APlus 5-Year Research Audit - READ ONLY
echo ============================================================

"%PYTHON%" research\historical_data_audit.py --project-root "%~dp0"
if errorlevel 1 exit /b %errorlevel%

"%PYTHON%" research\option_history_audit.py --project-root "%~dp0"
if errorlevel 1 exit /b %errorlevel%

"%PYTHON%" research\monthly_stock_performance.py --project-root "%~dp0"
if errorlevel 1 exit /b %errorlevel%

"%PYTHON%" research\backtest_validation.py --project-root "%~dp0"
if errorlevel 1 exit /b %errorlevel%

echo.
echo ============================================================
echo RESEARCH AUDIT COMPLETE
echo ============================================================
echo Outputs are under:
echo   data\research\5y_backtest\
echo.
echo No live scanner, Dhan, trading engine, paper journal,
echo dashboard, or Scheduled Task was modified.
exit /b 0
