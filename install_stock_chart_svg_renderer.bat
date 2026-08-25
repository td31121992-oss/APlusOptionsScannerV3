@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo APlus Stock Charts - SVG Renderer Fix
echo REPLACES ONLY CHART RENDERER - NO SCANNER/TRADING CHANGES
echo ==============================================================================
python install_stock_chart_svg_renderer.py
if errorlevel 1 (
 echo.
 echo INSTALL FAILED.
 pause
 exit /b 1
)
echo.
echo Stop ONLY dashboard CMD with Ctrl+C.
echo Restart:
echo   run_live_pnl_dashboard.bat
echo Then open:
echo   http://127.0.0.1:8765/stock-charts
pause
