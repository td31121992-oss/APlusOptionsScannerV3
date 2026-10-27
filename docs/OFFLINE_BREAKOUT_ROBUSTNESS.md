# Offline breakout robustness audit

This companion audit reads the validation events CSV and produces a JSON report covering train/test stability, per-symbol and per-session breadth, top-winner concentration, and timestamp consistency. It is read-only and never places orders.

## Run

From the repository root after generating validation events:

```powershell
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_offline_breakout_robustness.py" -v
& ".\.venv\Scripts\python.exe" scripts\offline_breakout_robustness.py
```

Optional paths:

```powershell
& ".\.venv\Scripts\python.exe" scripts\offline_breakout_robustness.py --events "data\research_replay\validation\breakout_validation_events.csv" --out "data\research_replay\validation\breakout_robustness_report.json"
```

## What it reports

- Train and held-out test metrics using only complete outcomes and the existing five-bar non-overlapping flag.
- A focused set of short-breakdown candidates across 3m/5m horizons and baseline, volume, trend, and pullback variants.
- Per-symbol average returns and best/worst symbols; number of symbols and sessions with positive/negative mean returns.
- Concentration of positive return sum attributable to the largest one and five winners.
- Timestamp timezone-awareness consistency, signal-entry-exit ordering, date coverage, and calendar-date gaps requiring review.

## Interpretation cautions

- Calendar gaps are flagged, not automatically classified as missing sessions: weekends and exchange holidays exist.
- The audit cannot prove that timestamps are correctly aligned to NSE time or that every expected candle is present. Compare a sample against the original Upstox API response and the exchange calendar.
- The winner-concentration measure is based on positive underlying percentage returns, not portfolio P&L. It does not model position sizing, costs, options Greeks, fills, or execution.
- Pullback variant entries occur after the original signal and are evaluated from the later entry price. Do not compare them as though entry occurred at the original breakout candle.
- This remains exploratory research on a short historical sample. Do not modify live or paper strategy rules or enable live orders based on this report.
