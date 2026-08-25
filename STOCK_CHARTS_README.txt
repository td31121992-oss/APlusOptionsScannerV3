APlus Stock Charts / Day Replay

- Persists one full F&O market-watch snapshot per minute.
- Shows all saved stocks by date, symbol and sector.
- Detail line chart plus all-stock gallery.
- ZERO additional Dhan API calls.
- Does not modify scanner/trading logic.

GitHub references reviewed:
1. tradingview/lightweight-charts — official Apache-2.0 financial chart library; useful for future candlestick/overlay upgrade.
2. marketcalls/stock-dashboard — useful dashboard architecture reference for watchlists, timeframes, EMA/RSI and auto-refresh.
3. savant-iai/tradingview-lightweight-charts-python — useful if later adding Python multi-pane charts, drawings and watchlists.

Current version intentionally uses dependency-free Canvas charts for stability. The stored history can later feed TradingView Lightweight Charts without changing the collector schema.
