@echo off
setlocal
cd /d "%~dp0"
schtasks /Create /TN "APlusOptionsScannerV3_StockChartHistory" /TR "cmd.exe /c \"\"%CD%\start_stock_chart_history.bat\"\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /RL LIMITED /F
if errorlevel 1 exit /b 1
echo SUCCESS: Stock chart history collector scheduled Mon-Fri 09:15.
pause
