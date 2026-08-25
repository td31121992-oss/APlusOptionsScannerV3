# APlus Stock Futures PAPER Research V1

Futures are PAPER/RESEARCH only. No live futures order path exists.

Signal inputs:
- data/reports/intraday_entry_ready.csv
- data/reports/leadership_v6_shadow_latest.json
- data/reports/fno_market_watch_latest.json

DIXON-like fast-continuation research override:
- quality >= 92
- clean trend >= 92
- relative volume >= 2x
- VWAP direction agrees

This override is FUTURES PAPER ONLY and does not alter the stock-options overheat gate.

API pressure control:
- underlying monitoring uses saved scanner reports (zero extra underlying quote calls)
- actual futures quote is fetched at paper entry
- actual futures quote is fetched at paper exit
- open futures are marked every 180 seconds by default
- entry candidates are quoted in one NSE_FNO batch

Default research exits:
- hard stop from scanner risk, fallback 0.45%
- trail activates +0.35%
- giveback 0.25%
- target +1.50%
- forced intraday exit 15:15

Capital:
- notional_value = futures price * lot quantity
- estimated_margin defaults to 25% of notional; it is not a broker margin statement

Run:
1. Keep normal APlus options scanner running.
2. Run install_stock_futures_paper_v1.bat once.
3. Run run_stock_futures_paper.bat in a separate CMD.
4. Optional: run run_stock_futures_paper_dashboard.bat.
5. Open http://127.0.0.1:8766
