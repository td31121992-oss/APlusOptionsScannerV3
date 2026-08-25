@echo off
cd /d "%~dp0"
echo APlus Stock Futures PAPER Research V1
echo FUTURES PAPER ONLY - NO LIVE FUTURES ORDERS
python run_stock_futures_paper.py --interval 30
pause
