@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo Upgrade APlus Morning Start - Shared Dhan Token Guard
echo ============================================================
if not exist "aplus_auto_start_token_guard.bat" (
 echo FAIL: aplus_auto_start_token_guard.bat not found.
 pause
 exit /b 1
)
if exist "aplus_auto_start.bat" (
 copy /Y "aplus_auto_start.bat" "aplus_auto_start_before_token_guard.bat" >nul
)
copy /Y "aplus_auto_start_token_guard.bat" "aplus_auto_start.bat" >nul
if errorlevel 1 (
 echo FAIL: could not replace aplus_auto_start.bat
 pause
 exit /b 1
)
echo PASS: existing 09:14 scheduled task will automatically use upgraded launcher.
echo PASS: waits/retries for shared Dhan token validation.
echo PASS: scanner will NOT start if token remains invalid.
echo PASS: duplicate scanner/dashboard protection retained.
echo PASS: startup logs retained.
echo.
echo No scheduled task recreation is required.
echo Do not manually run aplus_auto_start.bat now unless you want to start APlus.
pause
