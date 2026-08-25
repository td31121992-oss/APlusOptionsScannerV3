# APlus Winner-vs-Loser DNA V2 — Entry Reconstruction

This version fixes the main weakness of V1: the paper journal did not contain enough of the live market fingerprint.

V2 mines all saved project/back-up scanner evidence to reconstruct the entry state:
- rank / rank acceleration
- move acceleration
- Leadership V6
- V6.4 fast-track when available
- RVOL
- VWAP
- ADX / RSI / DI when available
- fresh breakout
- signal age
- fresh leg / reacceleration / stale move
- existing quality / clean / alignment scores

It uses only information at or before entry.

## True day holdout

Unlike V1, V2 performs a proper leave-one-day-out experiment:
1. Hold one day completely aside.
2. Discover the best rule using only the other days.
3. Freeze the rule.
4. Test that rule on the held-out day.

This is still a tiny dataset, so it is not proof of a production edge.

## No premium assumption

Option premium is not used as a DNA predictor.

## No future leakage

P&L/exit/MFE/MAE/post-entry movement are labels/outcomes only and are not used to construct winner DNA.

## Outputs

`data/reports/winner_loser_dna_v2/`
- reconstructed_entry_fingerprints.csv
- numeric_dna.csv
- categorical_dna.csv
- selective_rules_in_sample.csv
- true_leave_one_day_out.csv
- dna_v2_scores.csv
- selectivity_ladder.csv
- structured_sources.csv
- log_sources.csv
- winner_loser_dna_v2.html

No Dhan calls. No scanner modifications. No strategy changes.
