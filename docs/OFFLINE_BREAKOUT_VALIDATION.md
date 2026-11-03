# Offline breakout out-of-sample validation

This research-only tool extends the baseline replay in `scripts/offline_breakout_replay.py`. It reads local Upstox 3-minute/5-minute OHLCV CSVs and writes validation events and summaries. It does not connect to a broker, place orders, import the scanner, or modify trading/risk settings.

## Run locally

From the repository root:

```powershell
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_offline_breakout_validation.py" -v
& ".\.venv\Scripts\python.exe" scripts\offline_breakout_validation.py
```

Optional smoke test on a few symbols:

```powershell
& ".\.venv\Scripts\python.exe" scripts\offline_breakout_validation.py --symbols "TCS,RELIANCE,INFY" --intervals 3,5
```

Outputs default to `data/research_replay/validation/`:
- `breakout_validation_events.csv`: per-signal, per-filter, per-horizon outcome rows.
- `breakout_validation_summary.json`: train/test aggregates and input-file quality.

## Method

- **Chronological split:** for each input file, the earliest 70% of timestamp dates are marked train and the latest 30% test. No random shuffle. The test period must be reviewed separately and not used to choose filters.
- **Baseline:** close crossing the prior 20-bar high/low, using the existing replay signal definition.
- **Volume filter:** signal-candle volume at least 1.5 times the previous 20-bar average.
- **Trend filter:** signal close above/below the previous 20-bar close average, with that average above/below the preceding 20-bar average. Requires 40 prior bars.
- **Combined filter:** both volume and trend conditions.
- **Pullback entry:** within the next five bars, price retests the broken range level within 0.2% and closes back beyond it with a directionally aligned candle. Entry reference is that confirmation bar's close. This is a research definition, not live scanner logic.
- **Overlap control:** reports all signals and a spaced sample requiring five bars between signals for the same symbol/session/side/filter. All outcome horizons for one signal receive the same inclusion flag.
- **Horizons:** reports each 5-, 10-, and 15-bar outcome separately; incomplete future horizons are excluded from aggregate metrics.

## Interpretation limits

Returns are directional underlying-stock price percentages, not option-premium P&L. No spreads, fees, slippage, fill delay, stop/target execution, Greeks, or position sizing are modelled. OHLCV is not true bid/ask-at-price footprint data. Multiple symbols share market regimes and overlapping outcomes are not independent observations. The 19-session sample is exploratory; a chronological test split reduces but does not eliminate overfitting or regime bias. Verify timezone alignment and session completeness before relying on intraday results.

This tool is isolated research only. Do not change live or paper-trading rules from these outputs alone.
