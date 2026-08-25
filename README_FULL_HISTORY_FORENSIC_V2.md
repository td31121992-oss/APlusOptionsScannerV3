# APlus Full-History Forensic V2

This version deliberately does NOT blame option premium.

Primary question:
**For each losing option trade, did the underlying stock actually move in our predicted direction?**

It searches all saved CSV/JSON scanner files and backups for timestamped stock LTP or from-open movement data.

For every trade it tries to calculate direction-adjusted underlying movement:
- +1m
- +3m
- +5m
- +10m
- +15m
- +30m
- +60m
- MFE to 60m
- MAE to 60m
- post-exit continuation when data exists

Classification:
- CORRECT_STOCK_STRONG_CONTINUATION
- CORRECT_STOCK_BUT_LATE_CONTINUATION
- CORRECT_STOCK_MODEST_MOVE
- WRONG_STOCK_OR_BAD_ENTRY
- NO_CLEAR_EDGE
- NO_UNDERLYING_EVIDENCE

Then each option outcome becomes:
- WIN_CORRECT_STOCK
- LOSS_CORRECT_STOCK_OPTION_OR_EXIT_FAILED
- LOSS_CORRECT_STOCK_TIMING_OR_EXIT_FAILED
- LOSS_STOCK_RIGHT_BUT_MOVE_TOO_SMALL
- LOSS_BAD_STOCK_OR_ENTRY
- LOSS_NO_CLEAR_UNDERLYING_EDGE
- LOSS_NO_UNDERLYING_EVIDENCE

Premium is recorded but is NOT used to decide whether the stock call was right or wrong.

No Dhan calls. No production changes.
