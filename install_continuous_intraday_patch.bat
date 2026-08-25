@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PATCH=APlusOptionsScannerV3_continuous_intraday_patch.zip"
set "ZIP=%CD%\%PATCH%"
if not exist "%ZIP%" set "ZIP=%USERPROFILE%\Downloads\%PATCH%"

if not exist "main.py" (
  echo ERROR: Run this installer from the APlusOptionsScannerV3 project folder.
  goto :fail_no_restore
)
if not exist "config.py" (
  echo ERROR: config.py was not found.
  goto :fail_no_restore
)
if not exist "opening_momentum_scanner.py" (
  echo ERROR: opening_momentum_scanner.py was not found.
  goto :fail_no_restore
)
if not exist "safety_gate.py" (
  echo ERROR: safety_gate.py was not found. Install the Stock Options Safety Gate patch first.
  goto :fail_no_restore
)
if not exist "option_selector.py" (
  echo ERROR: option_selector.py was not found. Install the option-contract selection patch first.
  goto :fail_no_restore
)
if not exist "%ZIP%" (
  echo ERROR: %PATCH% not found in this folder or Downloads.
  goto :fail_no_restore
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "BACKUP=backup_before_continuous_intraday_!STAMP!"
set "TEMP_DIR=%TEMP%\aplus_continuous_intraday_!STAMP!"

mkdir "!BACKUP!" >nul 2>&1
mkdir "!TEMP_DIR!" >nul 2>&1

for %%F in (config.py main.py opening_momentum_scanner.py run_opening_momentum.bat) do (
  if exist "%%F" copy /Y "%%F" "!BACKUP!\%%F" >nul
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '!TEMP_DIR!' -Force"
if errorlevel 1 goto :rollback

for %%F in (config.py main.py opening_momentum_scanner.py intraday_movement_engine.py continuous_intraday_self_test.py run_intraday_movement.bat run_opening_momentum.bat CONTINUOUS_INTRADAY_MOVEMENT_PATCH.txt intraday_movement.env.example) do (
  if not exist "!TEMP_DIR!\%%F" (
    echo ERROR: Patch file %%F missing from ZIP.
    goto :rollback
  )
  copy /Y "!TEMP_DIR!\%%F" "%%F" >nul
  if errorlevel 1 goto :rollback
)

python -m py_compile config.py main.py opening_momentum_scanner.py intraday_movement_engine.py continuous_intraday_self_test.py
if errorlevel 1 goto :rollback

python -c "import config, intraday_movement_engine, opening_momentum_scanner, main; print('Continuous Intraday patch imports OK')"
if errorlevel 1 goto :rollback

python continuous_intraday_self_test.py
if errorlevel 1 goto :rollback

rmdir /S /Q "!TEMP_DIR!" >nul 2>&1

echo.
echo ============================================================
echo SUCCESS: Continuous Intraday Movement patch installed.
echo Backup: !BACKUP!
echo ============================================================
echo.
echo Start the full-day PAPER scanner with:
echo   run_intraday_movement.bat
echo or:
echo   python main.py --intraday-movement
echo.
echo One-cycle test:
echo   python main.py --intraday-once
echo.
echo IMPORTANT: .env was NOT changed.
echo Live orders remain disabled.
exit /b 0

:rollback
echo.
echo ERROR: Installation validation failed. Restoring overwritten files...
for %%F in (config.py main.py opening_momentum_scanner.py run_opening_momentum.bat) do (
  if exist "!BACKUP!\%%F" copy /Y "!BACKUP!\%%F" "%%F" >nul
)
for %%F in (intraday_movement_engine.py continuous_intraday_self_test.py run_intraday_movement.bat CONTINUOUS_INTRADAY_MOVEMENT_PATCH.txt intraday_movement.env.example) do (
  if exist "%%F" del /Q "%%F" >nul 2>&1
)
rmdir /S /Q "!TEMP_DIR!" >nul 2>&1
echo Rollback completed. Backup retained at !BACKUP!
exit /b 1

:fail_no_restore
exit /b 1
