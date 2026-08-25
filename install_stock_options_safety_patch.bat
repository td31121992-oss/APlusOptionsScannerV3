@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo ============================================================
echo APlus V3 - Stock Options Safety Gate Patch Installer
echo ============================================================
echo.
echo This installer DOES NOT modify .env or copy credentials.
echo.

set "PROJECT=%CD%"
set "ZIP_NAME=APlusOptionsScannerV3_stock_options_safety_patch.zip"
set "ZIP_PATH=%PROJECT%\%ZIP_NAME%"

if not exist "%PROJECT%\main.py" (
    echo ERROR: main.py was not found in:
    echo   %PROJECT%
    echo.
    echo Run this installer inside the APlusOptionsScannerV3 folder.
    exit /b 1
)

for %%F in (
    "opening_momentum_scanner.py"
    "core\dhan_client.py"
    "analytics\models.py"
    "trade_engine.py"
    "report_engine.py"
) do (
    if not exist "%PROJECT%\%%~F" (
        echo ERROR: Required project file is missing:
        echo   %%~F
        exit /b 1
    )
)

if not exist "%ZIP_PATH%" (
    if exist "%USERPROFILE%\Downloads\%ZIP_NAME%" (
        set "ZIP_PATH=%USERPROFILE%\Downloads\%ZIP_NAME%"
    ) else (
        echo ERROR: Could not find:
        echo   %ZIP_NAME%
        echo.
        echo Place the ZIP in the project folder or Windows Downloads.
        exit /b 1
    )
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "BACKUP=%PROJECT%\backup_before_stock_options_safety_%STAMP%"
set "TEMP_DIR=%TEMP%\aplus_stock_options_safety_%RANDOM%_%RANDOM%"

mkdir "%BACKUP%" >nul 2>&1
mkdir "%BACKUP%\core" >nul 2>&1
mkdir "%BACKUP%\analytics" >nul 2>&1

copy /Y "%PROJECT%\opening_momentum_scanner.py" "%BACKUP%\opening_momentum_scanner.py" >nul
copy /Y "%PROJECT%\core\dhan_client.py" "%BACKUP%\core\dhan_client.py" >nul
copy /Y "%PROJECT%\analytics\models.py" "%BACKUP%\analytics\models.py" >nul
copy /Y "%PROJECT%\trade_engine.py" "%BACKUP%\trade_engine.py" >nul
copy /Y "%PROJECT%\report_engine.py" "%BACKUP%\report_engine.py" >nul

set "HAD_SAFETY_GATE=0"
if exist "%PROJECT%\safety_gate.py" (
    set "HAD_SAFETY_GATE=1"
    copy /Y "%PROJECT%\safety_gate.py" "%BACKUP%\safety_gate.py" >nul
)

echo Extracting patch...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%TEMP_DIR%' -Force"
if errorlevel 1 (
    echo ERROR: ZIP extraction failed.
    exit /b 1
)

for %%F in (
    "safety_gate.py"
    "opening_momentum_scanner.py"
    "core\dhan_client.py"
    "analytics\models.py"
    "trade_engine.py"
    "report_engine.py"
    "safety_gate.env.example"
    "safety_gate_self_test.py"
    "STOCK_OPTIONS_SAFETY_PATCH.txt"
) do (
    if not exist "%TEMP_DIR%\%%~F" (
        echo ERROR: Patch file is missing:
        echo   %%~F
        goto :rollback
    )
)

echo Installing safety engine and integrations...
copy /Y "%TEMP_DIR%\safety_gate.py" "%PROJECT%\safety_gate.py" >nul
copy /Y "%TEMP_DIR%\opening_momentum_scanner.py" "%PROJECT%\opening_momentum_scanner.py" >nul
copy /Y "%TEMP_DIR%\core\dhan_client.py" "%PROJECT%\core\dhan_client.py" >nul
copy /Y "%TEMP_DIR%\analytics\models.py" "%PROJECT%\analytics\models.py" >nul
copy /Y "%TEMP_DIR%\trade_engine.py" "%PROJECT%\trade_engine.py" >nul
copy /Y "%TEMP_DIR%\report_engine.py" "%PROJECT%\report_engine.py" >nul
copy /Y "%TEMP_DIR%\safety_gate.env.example" "%PROJECT%\safety_gate.env.example" >nul
copy /Y "%TEMP_DIR%\safety_gate_self_test.py" "%PROJECT%\safety_gate_self_test.py" >nul
copy /Y "%TEMP_DIR%\STOCK_OPTIONS_SAFETY_PATCH.txt" "%PROJECT%\STOCK_OPTIONS_SAFETY_PATCH.txt" >nul

if not exist "%PROJECT%\data\safety" mkdir "%PROJECT%\data\safety" >nul 2>&1

for %%F in (
    "corporate_events.csv"
    "mwpl_status.csv"
    "nse_holidays.csv"
    "portfolio_state.json"
) do (
    if not exist "%PROJECT%\data\safety\%%~F" (
        copy /Y "%TEMP_DIR%\data\safety\%%~F" "%PROJECT%\data\safety\%%~F" >nul
    ) else (
        echo Preserved existing data\safety\%%~F
    )
)

echo Compiling patched Python files...
python -m py_compile ^
  "%PROJECT%\safety_gate.py" ^
  "%PROJECT%\opening_momentum_scanner.py" ^
  "%PROJECT%\core\dhan_client.py" ^
  "%PROJECT%\analytics\models.py" ^
  "%PROJECT%\trade_engine.py" ^
  "%PROJECT%\report_engine.py"
if errorlevel 1 (
    echo ERROR: Python compilation failed.
    goto :rollback
)

echo Checking project imports...
python -c "from safety_gate import SafetyGateEngine; from opening_momentum_scanner import OpeningMomentumScanner; from trade_engine import TradeEngine; from report_engine import ReportEngine; from core.dhan_client import DhanClient; print('Stock options safety patch imports OK')"
if errorlevel 1 (
    echo ERROR: Project import check failed.
    goto :rollback
)

echo Running offline safety behavior tests...
python "%PROJECT%\safety_gate_self_test.py"
if errorlevel 1 (
    echo ERROR: Offline safety tests failed.
    goto :rollback
)

rmdir /S /Q "%TEMP_DIR%" >nul 2>&1

echo.
echo SUCCESS: Stock Options Safety Gate Patch installed.
echo.
echo Backup saved at:
echo   %BACKUP%
echo.
echo IMPORTANT:
echo   1. The installer did not modify .env.
echo   2. Populate data\safety\corporate_events.csv
echo   3. Populate data\safety\mwpl_status.csv
echo   4. Populate data\safety\nse_holidays.csv
echo   5. Set today's date in data\safety\portfolio_state.json
echo.
echo Start in default PAPER_OBSERVE mode:
echo   python main.py --opening-once
echo.
echo Read:
echo   STOCK_OPTIONS_SAFETY_PATCH.txt
echo.
exit /b 0

:rollback
echo.
echo INSTALLATION FAILED. Restoring backed-up project files...
copy /Y "%BACKUP%\opening_momentum_scanner.py" "%PROJECT%\opening_momentum_scanner.py" >nul
copy /Y "%BACKUP%\core\dhan_client.py" "%PROJECT%\core\dhan_client.py" >nul
copy /Y "%BACKUP%\analytics\models.py" "%PROJECT%\analytics\models.py" >nul
copy /Y "%BACKUP%\trade_engine.py" "%PROJECT%\trade_engine.py" >nul
copy /Y "%BACKUP%\report_engine.py" "%PROJECT%\report_engine.py" >nul

if "%HAD_SAFETY_GATE%"=="1" (
    copy /Y "%BACKUP%\safety_gate.py" "%PROJECT%\safety_gate.py" >nul
) else (
    del /Q "%PROJECT%\safety_gate.py" >nul 2>&1
)

rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
echo Previous Python files restored.
exit /b 1
