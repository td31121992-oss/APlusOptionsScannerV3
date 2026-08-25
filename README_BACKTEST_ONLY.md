# APlus Backtest Research Kit — READ ONLY

This package is deliberately **not an installer**.

It does not patch:
- opening_momentum_scanner.py
- main.py
- option_selector.py
- safety_gate.py
- paper_trade_journal.py
- dashboards
- Windows Scheduled Tasks

## Purpose

Backtest an APlus-style **underlying stock-selection layer** using historical OHLCV candles and add deterministic candle/chart pattern research.

Signals combine:
- actual move from the session open
- VWAP alignment
- HH/HL or LH/LL structure
- relative volume
- opening-range breakout/breakdown
- candle confirmation
- EMA trend alignment

Pattern research includes:
- bullish/bearish engulfing
- hammer / shooting star
- doji / marubozu
- inside / outside bar
- NR4 / NR7
- expansion candle
- HH/HL and LH/LL structure
- range breakout/breakdown
- opening-range breakout/breakdown

## Run today

Copy this whole folder into the APlusOptionsScannerV3 project root, or copy the files directly there.

First:
    backtest_data_preflight.bat

Then:
    run_backtest_candle_chart_strategy.bat

If auto-discovery does not find historical candles:
    python backtest_candle_chart_strategy.py --input "PATH_TO_HISTORICAL_CANDLES"

Expected columns:
    symbol,timestamp,open,high,low,close,volume

CSV and Parquet are supported.

## Outputs

Only this folder is written:
    data/backtest_research/

Files:
- signals.csv
- summary.csv
- pattern_stats.csv
- run_manifest.json

## Important

This measures the *underlying directional move* after a candidate signal. It does not pretend that underlying % return equals option P&L.

Exact CE/PE P&L needs historical option-contract candles aligned to the signal time and selected strike/expiry. That should be a separate option replay stage.

Current APlus production candidates already use movement from 09:15, relative volume, VWAP, opening-range behavior and trade-quality/movement-capture scoring. The research kit mirrors those families conceptually, but it does not modify or replace production strategy code.
