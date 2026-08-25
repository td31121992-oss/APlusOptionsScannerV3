# APlus Stock Selection V2

Every scanner cycle now uses this sequence:

1. Rank the full F&O equity universe by LTP versus today's market open.
2. Keep the dynamic Top-5 UP and Top-5 DOWN stocks as trade-eligible.
3. Top-5 UP can only become BULLISH / CE entries.
4. Top-5 DOWN can only become BEARISH / PE entries.
5. Top-5 membership is not an automatic trade.
6. The existing setup must still be actionable.
7. V2 verifies the move is alive now using 5m/10m/15m continuation, participation and trend retention.
8. There is no daily trade-count quota.
9. Existing open positions keep their normal exit/runner management even if a stock later leaves the Top-5.
10. PAPER ONLY.

Evidence files:
- data/reports/intraday_stock_selection_v2.csv
- data/reports/intraday_stock_selection_v2_latest.json
- data/reports/intraday_movement_latest.json (contains the full stock_selection_v2 audit block)
