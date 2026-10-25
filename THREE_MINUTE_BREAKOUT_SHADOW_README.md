# 3-Minute Breakout/Breakdown Shadow Classifier

## Scope and safety
This is an isolated research component. It is not imported by the production scanner,
does not call Dhan or Upstox, does not create paper trades, and cannot authorize a trade.
Do not merge it into scanner entry logic until historical replay and outcomes are
reconciled against the complete current-day ledger and dashboard/history.

## Components
- aggregate_three_minute_bars builds 09:15-aligned candles from 1-minute bars.
  Incomplete buckets and missing-minute buckets are omitted; times at or after 15:30
  are ignored. Duplicate timestamps keep the last supplied row.
- same_slot_relative_volume compares current 3-minute volume to the median volume for
  that same time slot over prior sessions. Insufficient history returns None and blocks
  confirmation instead of assuming normal volume.
- classify_breakout_breakdown detects closes beyond the previous five completed bars
  and scores relative volume, candle close/body, short-term direction, VWAP alignment,
  and excessive VWAP extension. Results are labels for research only.
- evaluate_forward_outcome calculates underlying-price MFE/MAE and a fixed-horizon
  close return. These are not option-premium predictions or exit instructions.
- append_shadow_record appends JSONL to a caller-specified separate ledger and refuses
  signals that claim trade authority.

## Local tests
From repository root, run:
python -m unittest discover -s tests -p "test_breakout_breakdown_shadow.py" -v

Tests use synthetic data and the standard library; no API credentials are required.

## Next integration gate
Before wiring into opening_momentum_scanner.py, add a shadow-only adapter using the
existing shortlist and a separate, budgeted 1-minute request path. Validate same-slot
volume from at least five prior sessions, timestamp/session boundaries, false breaks,
follow-through, MFE/MAE and missed candidates. Do not change the current entry gate,
paper-trade journal, or order behaviour during validation.


## Historical replay runner (read-only)
The branch also includes:
- `run_three_minute_breakout_shadow_replay.py`: downloads up to 30 calendar days of 1-minute underlying OHLCV using the existing Upstox client, aggregates complete 3-minute bars, runs the classifier, and records candidate outcomes.
- `run_three_minute_breakout_shadow_replay.bat`: Windows launcher; uses the repository virtual environment when present.

Run from the repository root after pulling this research branch:
```powershell
.\.venv\Scripts\python.exe .\run_three_minute_breakout_shadow_replay.py --days 28
```
For a small connectivity check, use `--limit 5`; this is not a complete-universe replay.
Outputs are written under `data/three_minute_shadow_replay/`: raw 1m OHLCV, aggregated 3m OHLCV, candidate/outcome CSV and JSONL, and `summary.json` with per-symbol coverage and failures. The script never writes to the production paper-trade journal and all candidate records carry `shadow_only=true` and `trade_authorized=false`.

Interpretation safeguards:
- Historical 1-minute candles are retrieved for a maximum of 30 calendar days per run because the Upstox V3 API's 1–15 minute historical retrieval limit is one month.
- Relative volume is matched by actual 3-minute wall-clock slot and requires at least five prior sessions; missing slot data does not count as a match.
- Forward outcomes stop at missing 3-minute buckets and require five consecutive future bars for a complete 5-bar outcome.
- The current script measures underlying-stock movement (MFE/MAE and horizon close return), not option-premium return, slippage, brokerage, or net P&L.
- Do not claim profitability or consider production integration until `summary.json` shows adequate data coverage and outcomes are independently reconciled.
