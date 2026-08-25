# APlus Winner-vs-Loser DNA V1

Purpose: identify which **entry-time** characteristics separate the historical winners from losers.

This intentionally does NOT use:
- exit reason
- P&L magnitude
- return after the trade
- MFE/MAE
- post-entry underlying movement
- post-exit movement

Those are outcomes, not predictors.

Premium is recorded in the source history but is **excluded from the default DNA score and rule search**.

Outputs:
- winner_loser_numeric_dna.csv
- winner_loser_categorical_dna.csv
- selective_rules_in_sample.csv
- selective_rules_day_check.csv
- trade_dna_scores.csv
- selectivity_ladder.csv
- winner_loser_dna.html

Interpretation warning:
With about 15 winners and only 5 recovered trading days, high in-sample win rates can easily be overfit. A rule should not be promoted to production solely because it looks excellent historically. It must survive new forward paper sessions.

The user's 204-winner / 15-loser target is treated as an aspiration to test, not something the script assumes is achievable.
