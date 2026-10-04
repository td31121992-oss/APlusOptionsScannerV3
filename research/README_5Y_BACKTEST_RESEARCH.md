# APlus 5-Year Backtest & Historical Research Foundation

This package is **research-only**. It does not modify the live scanner, trading engine, Dhan authorization, paper-trade journal, dashboards, or Windows watchdog tasks.

## What this adds

- A deterministic audit of the historical datasets already present under `data/`.
- Coverage checks for the requested 5-year research window.
- A monthly stock-performance report using the first and last available trading observations in each month.
- A strict separation between underlying-stock research and exact option-contract replay.
- Walk-forward / out-of-sample date-split utilities so strategy research cannot silently train on future data.
- A machine-readable research gap report identifying missing years, fields, and option-history requirements.

## Important limitation

This commit does **not** claim that five years of historical data has been downloaded. It audits and processes data that actually exists.

Exact option P&L requires historical option-contract observations (timestamp, security ID/trading symbol, expiry, strike, CE/PE, LTP/OHLC and preferably bid/ask, OI, volume and IV). Underlying equity candles alone cannot be converted into truthful historical CE/PE P&L.

## Run

From the project root:

```powershell
.\.venv\Scripts\python.exe research\historical_data_audit.py --project-root .
.\.venv\Scripts\python.exe research\monthly_stock_performance.py --project-root .
.\.venv\Scripts\python.exe research\backtest_validation.py --project-root .
```

The scripts write only under `data/research/5y_backtest/`.

No Dhan API calls are made by these research utilities.
