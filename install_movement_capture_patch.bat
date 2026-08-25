@echo off
setlocal EnableExtensions

echo ============================================================
echo APlus V3 - Movement Capture Patch Installer
echo ============================================================
echo.

set "PROJECT=%CD%"
set "ZIP_NAME=APlusOptionsScannerV3_movement_capture_patch.zip"
set "ZIP_PATH=%PROJECT%\%ZIP_NAME%"

if not exist "%PROJECT%\main.py" (
    echo ERROR: main.py was not found in:
    echo   %PROJECT%
    echo.
    echo Run this installer inside the APlusOptionsScannerV3 folder.
    exit /b 1
)

if not exist "%PROJECT%\opening_momentum_scanner.py" (
    echo ERROR: opening_momentum_scanner.py was not found.
    echo Install the Opening Momentum Scanner first.
    exit /b 1
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
set "BACKUP=%PROJECT%\backup_before_movement_capture_%STAMP%"
set "TEMP_DIR=%TEMP%\aplus_movement_capture_%RANDOM%_%RANDOM%"

mkdir "%BACKUP%" >nul 2>&1
copy /Y "%PROJECT%\opening_momentum_scanner.py" "%BACKUP%\opening_momentum_scanner.py" >nul

echo Extracting patch...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%TEMP_DIR%' -Force"
if errorlevel 1 (
    echo ERROR: ZIP extraction failed.
    exit /b 1
)

if not exist "%TEMP_DIR%\opening_momentum_scanner.py" (
    echo ERROR: opening_momentum_scanner.py is missing from the patch.
    rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
    exit /b 1
)

echo Installing updated scanner...
copy /Y "%TEMP_DIR%\opening_momentum_scanner.py" "%PROJECT%\opening_momentum_scanner.py" >nul
if exist "%TEMP_DIR%\MOVEMENT_CAPTURE_PATCH.txt" (
    copy /Y "%TEMP_DIR%\MOVEMENT_CAPTURE_PATCH.txt" "%PROJECT%\MOVEMENT_CAPTURE_PATCH.txt" >nul
)

echo Compiling...
python -m py_compile "%PROJECT%\opening_momentum_scanner.py"
if errorlevel 1 (
    echo.
    echo ERROR: Compilation failed. Restoring the previous scanner...
    copy /Y "%BACKUP%\opening_momentum_scanner.py" "%PROJECT%\opening_momentum_scanner.py" >nul
    rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
    exit /b 1
)

echo Checking imports...
python -c "from opening_momentum_scanner import OpeningMomentumScanner, MomentumCandidate; print('Movement Capture patch imports OK')"
if errorlevel 1 (
    echo.
    echo ERROR: Import check failed. Restoring the previous scanner...
    copy /Y "%BACKUP%\opening_momentum_scanner.py" "%PROJECT%\opening_momentum_scanner.py" >nul
    rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
    exit /b 1
)

rmdir /S /Q "%TEMP_DIR%" >nul 2>&1

echo.
echo SUCCESS: Movement Capture patch installed.
echo Backup saved at:
echo   %BACKUP%
echo.
echo Test:
echo   python main.py --opening-once
echo.
echo Reports:
echo   data\reports\opening_momentum_early_entries.csv
echo   data\reports\opening_momentum_wait_for_pullback.csv
echo.
endlocal
