@echo off
setlocal
cd /d "%~dp0"
echo ============================================================================================================
echo APlus Zero-Trade Forensic + Silence Research Telegram
echo ============================================================================================================
python install_disable_research_telegram.py
if errorlevel 1 (
 echo.
 echo TELEGRAM FIX FAILED.
 pause
 exit /b 1
)
echo.
python verify_telegram_alert_policy.py
if errorlevel 1 (
 echo.
 echo VERIFY FAILED.
 pause
 exit /b 2
)
echo.
python forensic_zero_trades_20260821.py
echo.
echo COMPLETE
echo Restart ONLY technical alert engine to load Telegram silence.
echo ENTRY/EXIT Telegram and scanner health alerts remain enabled.
pause
