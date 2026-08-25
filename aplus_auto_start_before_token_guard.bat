@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "data\logs" mkdir "data\logs"
set "LOG=data\logs\aplus_auto_start.log"

echo.>>"%LOG%"
echo ============================================================>>"%LOG%"
echo [%date% %time%] APlus automatic morning startup>>"%LOG%"

rem Do not start a duplicate scanner from this project.
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter ""Name='python.exe' OR Name='pythonw.exe'"" -ErrorAction SilentlyContinue ^| Where-Object { $_.CommandLine -and $_.CommandLine -match 'APlusOptionsScannerV3' -and $_.CommandLine -match 'main\.py' }; if($p){exit 0}else{exit 1}"
if not errorlevel 1 (
  echo [%date% %time%] Scanner already running - duplicate start skipped.>>"%LOG%"
) else (
  if not exist "run_intraday_movement.bat" (
    echo [%date% %time%] ERROR: run_intraday_movement.bat not found.>>"%LOG%"
    exit /b 2
  )
  echo [%date% %time%] Starting APlus scanner...>>"%LOG%"
  start "APlus Intraday Scanner" /min cmd /c "cd /d ""%~dp0"" && call run_intraday_movement.bat >> ""data\logs\aplus_scanner_console.log"" 2>&1"
)

rem Give the scanner time to initialize, then verify process presence.
timeout /t 20 /nobreak >nul
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter ""Name='python.exe' OR Name='pythonw.exe'"" -ErrorAction SilentlyContinue ^| Where-Object { $_.CommandLine -and $_.CommandLine -match 'APlusOptionsScannerV3' -and $_.CommandLine -match 'main\.py' }; if($p){exit 0}else{exit 1}"
if errorlevel 1 (
  echo [%date% %time%] WARNING: scanner process not detected after startup. Check data\logs\aplus_scanner_console.log>>"%LOG%"
) else (
  echo [%date% %time%] PASS: scanner process detected.>>"%LOG%"
)

rem Start dashboard only if it is not already listening on the normal local dashboard port/process.
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter ""Name='python.exe' OR Name='pythonw.exe'"" -ErrorAction SilentlyContinue ^| Where-Object { $_.CommandLine -and $_.CommandLine -match 'APlusOptionsScannerV3' -and $_.CommandLine -match 'aplus_live_pnl_dashboard\.py' }; if($p){exit 0}else{exit 1}"
if not errorlevel 1 (
  echo [%date% %time%] Dashboard already running - duplicate start skipped.>>"%LOG%"
) else (
  if exist "run_live_pnl_dashboard.bat" (
    echo [%date% %time%] Starting APlus Live Trading Terminal...>>"%LOG%"
    start "APlus Live Trading Terminal" /min cmd /c "cd /d ""%~dp0"" && call run_live_pnl_dashboard.bat >> ""data\logs\aplus_dashboard_console.log"" 2>&1"
  ) else (
    echo [%date% %time%] WARNING: run_live_pnl_dashboard.bat not found.>>"%LOG%"
  )
)

echo [%date% %time%] Morning launcher finished.>>"%LOG%"
exit /b 0
