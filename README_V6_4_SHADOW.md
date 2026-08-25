# APlus Leadership V6.4 SHADOW

Research-only companion. It does not patch `opening_momentum_scanner.py`.

## Four areas tested

1. Leadership Fast Track
2. Cheap/wide option premium fragility
3. Fresh leg vs stale move vs reacceleration
4. Futures PAPER recommendation when stock signal is strong but option lane is blocked/fragile

## Core starting thresholds (research only)

- Fast quality >= 90
- Clean trend >= 90
- RVOL >= 2x
- Alignment >= 55
- VWAP direction must agree
- New leg: 5m directional +0.25% with rank improvement >=5 or V6 confirmation
- New leg alternative: 10m directional +0.40%
- Stale age: >=60 minutes without fresh acceleration
- Cheap option flag: premium <= Rs 15
- Wide spread flag: >3%

These are NOT production thresholds. They are intentionally isolated for forward validation.

## Output

- data/reports/leadership_v6_4_shadow_latest.csv/json
- data/reports/leadership_v6_4_futures_bridge_latest.csv
- data/leadership_v6_4_shadow/events.csv
- data/reports/leadership_v6_4_forensic_2026-08-24.csv

## Start

1. Copy all package files into APlusOptionsScannerV3 root.
2. Run install_leadership_v6_4_shadow.bat.
3. Run run_leadership_v6_4_replay_24aug.bat.
4. During market hours run run_leadership_v6_4_shadow.bat in a separate CMD.

Existing stock-options scanner remains unchanged.
