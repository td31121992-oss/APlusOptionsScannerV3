@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PATCH=APlusOptionsScannerV3_full_session_trade_risk_10_patch.zip"
set "ZIP=%CD%\%PATCH%"
if not exist "%ZIP%" set "ZIP=%USERPROFILE%\Downloads\%PATCH%"

if not exist "main.py" (
  echo ERROR: Run this installer from the APlusOptionsScannerV3 project folder.
  goto :fail_no_restore
)
if not exist "opening_momentum_scanner.py" (
  echo ERROR: opening_momentum_scanner.py was not found.
  goto :fail_no_restore
)
if not exist "option_selector.py" (
  echo ERROR: option_selector.py was not found.
  goto :fail_no_restore
)
if not exist "safety_gate.py" (
  echo ERROR: safety_gate.py was not found. Install the stock-options safety patch first.
  goto :fail_no_restore
)
if not exist "%ZIP%" (
  echo ERROR: %PATCH% not found in this folder or Downloads.
  goto :fail_no_restore
)

set "STAMP=%RANDOM%_%RANDOM%"
set "BACKUP=backup_before_trade_risk_10_!STAMP!"
set "TEMP_DIR=%TEMP%\aplus_trade_risk_10_!STAMP!"
mkdir "!BACKUP!" >nul 2>&1
mkdir "!TEMP_DIR!" >nul 2>&1

for %%F in (config.py main.py opening_momentum_scanner.py intraday_movement_engine.py paper_trade_journal.py option_selector.py safety_gate.py safety_gate_self_test.py continuous_intraday_self_test.py run_intraday_movement.bat run_opening_momentum.bat intraday_movement.env.example safety_gate.env.example) do (
  if exist "%%F" copy /Y "%%F" "!BACKUP!\%%F" >nul
)

python -c "import zipfile; zipfile.ZipFile(r'%ZIP%').extractall(r'!TEMP_DIR!')"
if errorlevel 1 goto :rollback

for %%F in (config.py main.py opening_momentum_scanner.py intraday_movement_engine.py paper_trade_journal.py option_selector.py safety_gate.py safety_gate_self_test.py continuous_intraday_self_test.py trade_risk_self_test.py run_intraday_movement.bat run_opening_momentum.bat intraday_movement.env.example safety_gate.env.example PER_TRADE_RISK_10_PATCH.txt) do (
  if not exist "!TEMP_DIR!\%%F" (
    echo ERROR: Patch file %%F missing from ZIP.
    goto :rollback
  )
  copy /Y "!TEMP_DIR!\%%F" "%%F" >nul
  if errorlevel 1 goto :rollback
)

python -m py_compile config.py main.py opening_momentum_scanner.py intraday_movement_engine.py paper_trade_journal.py option_selector.py safety_gate.py safety_gate_self_test.py continuous_intraday_self_test.py trade_risk_self_test.py
if errorlevel 1 goto :rollback

python trade_risk_self_test.py
if errorlevel 1 goto :rollback
python safety_gate_self_test.py
if errorlevel 1 goto :rollback
python continuous_intraday_self_test.py
if errorlevel 1 goto :rollback

rmdir /S /Q "!TEMP_DIR!" >nul 2>&1

echo.
echo ============================================================
echo SUCCESS: Full-session + per-trade 10%% risk patch installed.
echo Backup: !BACKUP!
echo ============================================================
echo.
echo Risk basis:
echo   selected option premium / capital required for THIS trade
echo   maximum planned trade risk = 10%%
echo.
echo Example:
echo   Rs 30,000 trade capital = Rs 3,000 max risk
echo.
echo IMPORTANT: .env was NOT changed.
echo Live orders remain disabled.
echo.
echo Restart scanner with:
echo   run_intraday_movement.bat
exit /b 0

:rollback
echo.
echo ERROR: Installation validation failed. Restoring overwritten files...
for %%F in (config.py main.py opening_momentum_scanner.py intraday_movement_engine.py paper_trade_journal.py option_selector.py safety_gate.py safety_gate_self_test.py continuous_intraday_self_test.py run_intraday_movement.bat run_opening_momentum.bat intraday_movement.env.example safety_gate.env.example) do (
  if exist "!BACKUP!\%%F" copy /Y "!BACKUP!\%%F" "%%F" >nul
)
for %%F in (trade_risk_self_test.py PER_TRADE_RISK_10_PATCH.txt) do (
  if exist "%%F" del /Q "%%F" >nul 2>&1
)
rmdir /S /Q "!TEMP_DIR!" >nul 2>&1
echo Rollback completed. Backup retained at !BACKUP!
exit /b 1

:fail_no_restore
exit /b 1
