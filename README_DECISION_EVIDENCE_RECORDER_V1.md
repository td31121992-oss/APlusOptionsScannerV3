# APlus Decision Evidence Recorder V1

This is the permanent evidence-capture layer for future strategy research.

It does **not** patch the production scanner.

It records:

- every ENTRY_READY candidate
- every FRESH_MOVEMENT candidate
- every WAIT_FOR_PULLBACK candidate
- every NEAR_MISS candidate
- Leadership V6 qualified candidates
- Leadership V6.4 fast-track candidates
- scanner.log conversion/fallback/safety evidence
- every actual paper entry
- every actual paper exit
- underlying path after each paper entry at +1/+3/+5/+10/+15/+30/+60 minutes

## Files

`data/decision_evidence/decision_events.csv`

`data/decision_evidence/candidate_snapshots.csv`

`data/decision_evidence/trade_underlying_path.csv`

`data/decision_evidence/recorder_state.json`

`data/decision_evidence/latest.json`

## Why separate process?

The production scanner has recently been repaired and is actively paper trading.
Keeping evidence capture separate means:
- no strategy threshold changes
- no new Dhan pressure
- no chance of recorder exceptions stopping scanner cycles
- easy removal/upgrade later

## Start

1. Extract into the APlusOptionsScannerV3 root.
2. Run `install_decision_evidence_recorder_v1.bat`.
3. Run `test_decision_evidence_recorder_once.bat`.
4. Then run `run_decision_evidence_recorder.bat` in a separate CMD and leave it running with the scanner.

This is the dataset future Winner-vs-Loser DNA versions should use.
