# Delta / Gamma Flip Shadow Research

**Status: isolated research only. No production integration.**

This folder adds a small Black-Scholes Greek calculator and a research-only
gamma-exposure zero-crossing estimator. It does not modify scanner selection,
entry quality, the paper-trade journal, dashboards, scheduled tasks, or orders.

## What is and is not available

- APlus option-chain snapshots contain spot, strike, CE/PE, IV and open interest.
- Delta and gamma can be model-estimated with spot, strike, IV, time to expiry,
  and an explicit risk-free-rate assumption.
- A dealer gamma-flip estimate requires signed dealer positioning. Open interest
  does **not** identify whether dealers are long or short each option.
- The calculator returns UNAVAILABLE unless each contract supplies an explicit
  dealer_position_sign (+1 long / -1 short). It does not infer dealer inventory.
- The exposure is an assumption-dependent proxy, not a verified exchange metric
  or a standalone trade signal.

## Validation plan

1. Run the isolated unit tests in a Python 3.10+ environment.
2. Audit local historical option-chain snapshots and the complete paper-trade
   ledger for timestamp-aligned data. The GitHub source tree does not establish
   that local runtime data files are available here.
3. If signed dealer-position data is unavailable, evaluate model Greeks, option
   premium response, underlying movement and time-to-expiry as separate features.
4. Replay the full reconciled ledger and report sample size, blocked winners,
   avoided losers, net P&L after costs, and results by symbol/expiry/time.
5. Keep this shadow-only unless out-of-sample evidence supports a change.

## Running tests

~~~sh
python -m unittest -v test_delta_gamma_flip_shadow.py
~~~
