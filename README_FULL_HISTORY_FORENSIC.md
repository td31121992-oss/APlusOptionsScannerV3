# APlus Full-History Profitability + Trade Forensic V1

This is the next priority before any new production tuning.

It scans all discoverable current + backup paper-trade CSV/JSON files, deduplicates trades, and compares winners vs losers from the first available trade day.

If `data/time_relative_rank_history/YYYY-MM-DD/rank_HHMM.csv` exists, it also reconstructs the underlying directional move after entry/exit.

Outputs:
- `data/reports/full_history_forensic/full_history_forensic.html`
- `all_trades_forensic.csv`
- `daily_summary.csv`
- `forensic_cause_summary.csv`
- `setup_summary.csv`
- `premium_band_summary.csv`
- `entry_time_summary.csv`
- `exit_reason_summary.csv`
- `overall_summary.json`

Loss classification is evidence-driven:
- FALSE_OPTION_STOP_UNDERLYING_CONTINUED
- BAD_OR_FAILED_UNDERLYING_SIGNAL
- OPTION_PREMIUM_FRAGILITY
- CHASE_OR_LATE_ENTRY
- LOSS_NEEDS_DEEP_REVIEW

Important: if underlying history is missing for older days, the tool reports evidence coverage rather than inventing a cause.

No Dhan calls. No production files modified. No strategy thresholds changed.
