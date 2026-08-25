@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==============================================================================
echo APlus BTST Automatic Evidence Scheduler
echo PAPER / RESEARCH ONLY - NO LIVE ORDERS
echo ==============================================================================
echo.
echo This creates two Windows Scheduled Tasks:
echo   1. APlusOptionsScannerV3_BTST_Candidates   - Mon-Fri at 14:45
echo   2. APlusOptionsScannerV3_BTST_NextMorning - Mon-Fri at 09:15
echo.
echo Project folder:
echo   %CD%
echo.

if not exist "run_btst_candidate_scanner.bat" (
    echo FAIL: run_btst_candidate_scanner.bat not found in:
    echo   %CD%
    echo.
    echo Run install_btst_research.bat first.
    pause
    exit /b 1
)

if not exist "run_btst_next_morning_tracker.bat" (
    echo FAIL: run_btst_next_morning_tracker.bat not found in:
    echo   %CD%
    echo.
    echo Run install_btst_research.bat first.
    pause
    exit /b 1
)

if not exist "data\logs" mkdir "data\logs"

rem ---------------------------------------------------------------------------
rem Wrapper 1: candidate evidence capture at 14:45
rem ---------------------------------------------------------------------------
> "btst_candidate_autostart.bat" (
    echo @echo off
    echo cd /d "%%~dp0"
    echo echo ============================================================ ^>^> "data\logs\btst_candidate_autostart.log"
    echo echo [%%date%% %%time%%] BTST candidate scheduled start ^>^> "data\logs\btst_candidate_autostart.log"
    echo call "run_btst_candidate_scanner.bat" ^>^> "data\logs\btst_candidate_console.log" 2^>^&1
    echo echo [%%date%% %%time%%] BTST candidate scheduled finish RC=%%errorlevel%% ^>^> "data\logs\btst_candidate_autostart.log"
)

rem ---------------------------------------------------------------------------
rem Wrapper 2: next-morning evidence tracking at 09:15
rem ---------------------------------------------------------------------------
> "btst_next_morning_autostart.bat" (
    echo @echo off
    echo cd /d "%%~dp0"
    echo echo ============================================================ ^>^> "data\logs\btst_next_morning_autostart.log"
    echo echo [%%date%% %%time%%] BTST next-morning scheduled start ^>^> "data\logs\btst_next_morning_autostart.log"
    echo call "run_btst_next_morning_tracker.bat" ^>^> "data\logs\btst_next_morning_console.log" 2^>^&1
    echo echo [%%date%% %%time%%] BTST next-morning scheduled finish RC=%%errorlevel%% ^>^> "data\logs\btst_next_morning_autostart.log"
)

set "CAND_TASK=APlusOptionsScannerV3_BTST_Candidates"
set "MORN_TASK=APlusOptionsScannerV3_BTST_NextMorning"

echo Creating/updating candidate task...
schtasks /Create /F /TN "%CAND_TASK%" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 14:45 /TR "cmd.exe /c \"\"%CD%\btst_candidate_autostart.bat\"\"" /RL LIMITED
if errorlevel 1 (
    echo FAIL: Could not create %CAND_TASK%
    pause
    exit /b 1
)

echo Creating/updating next-morning task...
schtasks /Create /F /TN "%MORN_TASK%" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /TR "cmd.exe /c \"\"%CD%\btst_next_morning_autostart.bat\"\"" /RL LIMITED
if errorlevel 1 (
    echo FAIL: Could not create %MORN_TASK%
    pause
    exit /b 1
)

echo.
echo ==============================================================================
echo SUCCESS: BTST AUTO EVIDENCE COLLECTION INSTALLED
echo ==============================================================================
echo Candidate scan : Monday-Friday at 14:45 IST
echo Morning tracker: Monday-Friday at 09:15 IST
echo.
echo Logs:
echo   data\logs\btst_candidate_autostart.log
echo   data\logs\btst_candidate_console.log
echo   data\logs\btst_next_morning_autostart.log
echo   data\logs\btst_next_morning_console.log
echo.
echo IMPORTANT:
echo The 14:45 task starts the candidate scanner, which continues through 15:20.
echo The 09:15 task starts the next-morning tracker, which continues through 10:00.
echo These are PAPER / RESEARCH evidence tasks only.
echo.
echo Verifying tasks...
echo.
schtasks /Query /TN "%CAND_TASK%" /V /FO LIST
echo.
schtasks /Query /TN "%MORN_TASK%" /V /FO LIST
echo.
pause
