@echo off
setlocal
cd /d "%~dp0"
echo ======================================================================================================================
echo APlus Safe Stock-Option Expiry Fallback
echo PAPER ONLY - PRESERVES PHYSICAL-SETTLEMENT SAFETY
echo ======================================================================================================================
python install_safe_expiry_fallback.py
if errorlevel 1 (
  echo.
  echo INSTALL FAILED - original restored automatically.
  pause
  exit /b 1
)
echo.
python -m py_compile opening_momentum_scanner.py core\option_chain.py safety_gate.py option_selector.py
if errorlevel 1 (
  echo COMPILE VERIFY FAILED.
  pause
  exit /b 2
)
echo.
echo COMPLETE.
echo IMPORTANT: restart run_intraday_movement.bat to load this fix.
echo Then search scanner.log for OPTION_EXPIRY_FALLBACK and PAPER conversion audit.
pause
