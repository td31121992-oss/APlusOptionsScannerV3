@echo off
setlocal EnableExtensions

echo ============================================================
echo APlus Options Scanner V3 - Option Contract Patch Installer
echo ============================================================
echo.

set "PROJECT=%CD%"
set "ZIP_NAME=APlusOptionsScannerV3_option_contract_selection.zip"
set "ZIP_PATH=%PROJECT%\%ZIP_NAME%"

if not exist "%PROJECT%\main.py" (
    echo ERROR: main.py was not found in:
    echo   %PROJECT%
    echo.
    echo Open Command Prompt in the APlusOptionsScannerV3 project folder,
    echo then run this installer again.
    exit /b 1
)

if not exist "%PROJECT%\analytics" (
    echo ERROR: analytics folder was not found.
    exit /b 1
)

if not exist "%PROJECT%\core" (
    echo ERROR: core folder was not found.
    exit /b 1
)

if not exist "%ZIP_PATH%" (
    if exist "%USERPROFILE%\Downloads\%ZIP_NAME%" (
        set "ZIP_PATH=%USERPROFILE%\Downloads\%ZIP_NAME%"
    ) else (
        echo ERROR: Could not find:
        echo   %ZIP_NAME%
        echo.
        echo Place the ZIP in this project folder or in Downloads.
        exit /b 1
    )
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "BACKUP=%PROJECT%\backup_before_option_patch_%STAMP%"
set "TEMP_DIR=%TEMP%\aplus_option_patch_%RANDOM%_%RANDOM%"

echo Project:
echo   %PROJECT%
echo ZIP:
echo   %ZIP_PATH%
echo Backup:
echo   %BACKUP%
echo.

mkdir "%BACKUP%\analytics" >nul 2>&1
mkdir "%BACKUP%\core" >nul 2>&1

if exist "%PROJECT%\analytics\models.py" copy /Y "%PROJECT%\analytics\models.py" "%BACKUP%\analytics\models.py" >nul
if exist "%PROJECT%\core\instrument_loader.py" copy /Y "%PROJECT%\core\instrument_loader.py" "%BACKUP%\core\instrument_loader.py" >nul
if exist "%PROJECT%\core\scanner.py" copy /Y "%PROJECT%\core\scanner.py" "%BACKUP%\core\scanner.py" >nul
if exist "%PROJECT%\option_selector.py" copy /Y "%PROJECT%\option_selector.py" "%BACKUP%\option_selector.py" >nul
if exist "%PROJECT%\trade_engine.py" copy /Y "%PROJECT%\trade_engine.py" "%BACKUP%\trade_engine.py" >nul
if exist "%PROJECT%\report_engine.py" copy /Y "%PROJECT%\report_engine.py" "%BACKUP%\report_engine.py" >nul

echo Extracting patch...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%TEMP_DIR%' -Force"
if errorlevel 1 (
    echo ERROR: ZIP extraction failed.
    exit /b 1
)

for %%F in (
    "%TEMP_DIR%\analytics\models.py"
    "%TEMP_DIR%\core\instrument_loader.py"
    "%TEMP_DIR%\core\scanner.py"
    "%TEMP_DIR%\option_selector.py"
    "%TEMP_DIR%\trade_engine.py"
    "%TEMP_DIR%\report_engine.py"
) do (
    if not exist "%%~F" (
        echo ERROR: Missing expected patch file:
        echo   %%~F
        rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
        exit /b 1
    )
)

echo Installing files...
copy /Y "%TEMP_DIR%\analytics\models.py" "%PROJECT%\analytics\models.py" >nul
copy /Y "%TEMP_DIR%\core\instrument_loader.py" "%PROJECT%\core\instrument_loader.py" >nul
copy /Y "%TEMP_DIR%\core\scanner.py" "%PROJECT%\core\scanner.py" >nul
copy /Y "%TEMP_DIR%\option_selector.py" "%PROJECT%\option_selector.py" >nul
copy /Y "%TEMP_DIR%\trade_engine.py" "%PROJECT%\trade_engine.py" >nul
copy /Y "%TEMP_DIR%\report_engine.py" "%PROJECT%\report_engine.py" >nul

echo Compiling installed files...
python -m py_compile ^
  "%PROJECT%\analytics\models.py" ^
  "%PROJECT%\core\instrument_loader.py" ^
  "%PROJECT%\core\scanner.py" ^
  "%PROJECT%\option_selector.py" ^
  "%PROJECT%\trade_engine.py" ^
  "%PROJECT%\report_engine.py"

if errorlevel 1 (
    echo.
    echo ERROR: Compilation failed.
    echo Original files are preserved in:
    echo   %BACKUP%
    rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
    exit /b 1
)

rmdir /S /Q "%TEMP_DIR%" >nul 2>&1

echo.
echo SUCCESS: Option contract selection patch installed and compiled.
echo Backup saved at:
echo   %BACKUP%
echo.
echo Next command:
echo   python main.py --once
echo.
endlocal
