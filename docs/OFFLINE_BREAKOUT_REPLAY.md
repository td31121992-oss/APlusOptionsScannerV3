# Offline breakout replay (research only)

This tool reads local Upstox 3-minute/5-minute OHLCV CSVs and writes research reports. It is isolated from the scanner and has no broker client, order placement, or configuration writes.

## Run locally

From the repository root:

```powershell
& ".\.venv\Scripts\python.exe" "scripts\offline_breakout_replay.py"
```

Optional quick run on a few symbols:

```powershell
& ".\.venv\Scripts\python.exe" "scripts\offline_breakout_replay.py" --symbols "TCS,RELIANCE,INFY" --intervals 3,5
```

Reports are written to `data/research_replay/`:
- `breakout_replay_events.csv`: signal-level outcomes at 5, 10, and 15 bars.
- `breakout_replay_summary.json`: aggregated results and file quality checks.

## Baseline definition

- Look back over the previous 20 bars, excluding the current candle.
- Long breakout: current close crosses above the prior 20-bar high; short breakdown: current close crosses below the prior 20-bar low.
- Volume-confirmed means current volume is at least 1.5 times the previous 20-bar average volume.
- Entry reference is the signal candle close. Outcome uses only following bars from the same timestamp-date group. A horizon without enough future bars is left unscored.
- MFE/MAE and directional return are underlying price percentages, not options P&L. For shorts, positive directional return means the underlying moved down.

## Validate before interpreting

The timestamp's date is used as the session grouping boundary. If source timestamps are UTC, confirm timezone/session alignment before relying on intraday results. The script reports file-level errors, but does not claim that every expected exchange candle is present. Check session completeness and missing intervals separately.

This is a simple research baseline, not the live scanner strategy. It does not model slippage, brokerage, taxes, spread, fills, option Greeks, option premium, or capital sizing. OHLCV candles do not provide true bid/ask-at-price footprint data. Do not use the results alone to change live or paper-trading rules.
