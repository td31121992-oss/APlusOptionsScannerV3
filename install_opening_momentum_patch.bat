@echo off
setlocal EnableExtensions

echo ============================================================
echo APlus V3 - Opening Momentum Patch Installer
echo ============================================================
echo.

set "PROJECT=%CD%"
set "ZIP_NAME=APlusOptionsScannerV3_opening_momentum_patch.zip"
set "ZIP_PATH=%PROJECT%\%ZIP_NAME%"

if not exist "%PROJECT%\main.py" (
    echo ERROR: main.py was not found in:
    echo   %PROJECT%
    echo.
    echo Open Command Prompt in the APlusOptionsScannerV3 folder
    echo and run this installer again.
    exit /b 1
)

if not exist "%PROJECT%\core\dhan_client.py" (
    echo ERROR: core\dhan_client.py was not found.
    exit /b 1
)

if not exist "%PROJECT%\option_selector.py" (
    echo ERROR: option_selector.py was not found.
    echo Install the option-contract selection patch first.
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
set "BACKUP=%PROJECT%\backup_before_opening_momentum_%STAMP%"
set "TEMP_DIR=%TEMP%\aplus_opening_patch_%RANDOM%_%RANDOM%"

mkdir "%BACKUP%\core" >nul 2>&1

if exist "%PROJECT%\config.py" copy /Y "%PROJECT%\config.py" "%BACKUP%\config.py" >nul
if exist "%PROJECT%\main.py" copy /Y "%PROJECT%\main.py" "%BACKUP%\main.py" >nul
if exist "%PROJECT%\core\dhan_client.py" copy /Y "%PROJECT%\core\dhan_client.py" "%BACKUP%\core\dhan_client.py" >nul
if exist "%PROJECT%\opening_momentum_scanner.py" copy /Y "%PROJECT%\opening_momentum_scanner.py" "%BACKUP%\opening_momentum_scanner.py" >nul
if exist "%PROJECT%\run_opening_momentum.bat" copy /Y "%PROJECT%\run_opening_momentum.bat" "%BACKUP%\run_opening_momentum.bat" >nul

echo Extracting patch...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%TEMP_DIR%' -Force"
if errorlevel 1 (
    echo ERROR: ZIP extraction failed.
    exit /b 1
)

for %%F in (
    "%TEMP_DIR%\config.py"
    "%TEMP_DIR%\main.py"
    "%TEMP_DIR%\core\dhan_client.py"
    "%TEMP_DIR%\opening_momentum_scanner.py"
    "%TEMP_DIR%\run_opening_momentum.bat"
) do (
    if not exist "%%~F" (
        echo ERROR: Missing expected patch file:
        echo   %%~F
        rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
        exit /b 1
    )
)

echo Installing files...
copy /Y "%TEMP_DIR%\config.py" "%PROJECT%\config.py" >nul
copy /Y "%TEMP_DIR%\main.py" "%PROJECT%\main.py" >nul
copy /Y "%TEMP_DIR%\core\dhan_client.py" "%PROJECT%\core\dhan_client.py" >nul
copy /Y "%TEMP_DIR%\opening_momentum_scanner.py" "%PROJECT%\opening_momentum_scanner.py" >nul
copy /Y "%TEMP_DIR%\run_opening_momentum.bat" "%PROJECT%\run_opening_momentum.bat" >nul
copy /Y "%TEMP_DIR%\opening_momentum.env.example" "%PROJECT%\opening_momentum.env.example" >nul
copy /Y "%TEMP_DIR%\OPENING_MOMENTUM_INSTALL.txt" "%PROJECT%\OPENING_MOMENTUM_INSTALL.txt" >nul

echo Compiling installed files...
python -m py_compile ^
  "%PROJECT%\config.py" ^
  "%PROJECT%\core\dhan_client.py" ^
  "%PROJECT%\opening_momentum_scanner.py" ^
  "%PROJECT%\main.py"

if errorlevel 1 (
    echo.
    echo ERROR: Compilation failed.
    echo Original files are preserved in:
    echo   %BACKUP%
    rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
    exit /b 1
)

echo Checking imports...
python -c "from config import AppConfig; from opening_momentum_scanner import OpeningMomentumScanner; from option_selector import OptionSelector; print('Opening Momentum patch imports OK')"
if errorlevel 1 (
    echo.
    echo ERROR: Import validation failed.
    echo Original files are preserved in:
    echo   %BACKUP%
    rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
    exit /b 1
)

rmdir /S /Q "%TEMP_DIR%" >nul 2>&1

echo.
echo SUCCESS: Opening Momentum Scanner installed and compiled.
echo Backup saved at:
echo   %BACKUP%
echo.
echo Test one cycle:
echo   python main.py --opening-once
echo.
echo Live opening session:
echo   run_opening_momentum.bat
echo.
endlocal
