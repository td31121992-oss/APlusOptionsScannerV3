# Delta / Gamma Flip Shadow Research

**Status: isolated research only. No production integration.**

This folder contains a Black-Scholes Greek calculator, a research-only gamma-exposure zero-crossing estimator, and a read-only local-data audit. It does not modify scanner selection, entry quality, the paper-trade journal, dashboards, scheduled tasks, or orders.

## What is and is not available

- APlus option-chain snapshots contain spot, strike, CE/PE, IV and open interest.
- Delta and gamma can be model-estimated with spot, strike, IV, time to expiry, and an explicit risk-free-rate assumption.
- A dealer gamma-flip estimate requires signed dealer positioning. Open interest does **not** identify whether dealers are long or short each option.
- The calculator returns UNAVAILABLE unless each contract supplies an explicit dealer_position_sign (+1 long / -1 short). It does not infer dealer inventory.
- The exposure is an assumption-dependent proxy, not a verified exchange metric or a standalone trade signal.
- Runtime files are ignored by Git via `.gitignore` (`data/` and logs). They can exist in the local project even though the GitHub source tree does not contain them.

## Read-only data preflight

Run this from the research folder against the local project checkout:

~~~sh
python shadow_data_audit.py --root "C:/Users/Aplus/Desktop/APlusOptionsScannerV3"
~~~

The script inventories paper-trade CSV/JSON ledgers, checks blank/duplicate trade IDs, compares the paper_trade_history CSV and JSON ID sets/counts when both are present, and reports available option-chain snapshot dates/symbols. It does not change source data. An optional report can be written with `--output <path>`.

Expected local sources include `data/reports/paper_trade_history.csv`, `data/reports/paper_trade_history.json`, `data/reports/paper_trades.csv`, `data/reports/paper_trades_latest.json`, `data/options_intelligence/YYYY-MM-DD/option_chain_snapshots.jsonl`, and `data/signal_snapshots/`. The audit also searches for the journal JSON by filename. It deliberately reports missing data instead of inventing rows or outcomes.

A clean preflight is necessary but **not sufficient** for strategy replay: the complete ledger must still be reconciled against dashboard/history evidence, and snapshot timestamps must be aligned with each trade's decision/entry time.

## Validation plan

1. Run the isolated unit tests in a Python 3.12 environment.
2. Audit local historical option-chain snapshots and the complete paper-trade ledger for timestamp-aligned data.
3. If signed dealer-position data is unavailable, evaluate model Greeks, option premium response, underlying movement and time-to-expiry as separate features.
4. Replay the full reconciled ledger and report sample size, blocked winners, avoided losers, net P&L after costs, and results by symbol/expiry/time.
5. Keep this shadow-only unless out-of-sample evidence supports a change.

## Running tests

~~~sh
python -m unittest -v test_delta_gamma_flip_shadow.py test_shadow_data_audit.py
~~~
