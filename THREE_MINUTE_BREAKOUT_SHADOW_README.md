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
