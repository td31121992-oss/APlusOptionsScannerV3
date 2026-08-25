APLUS LEADERSHIP ENGINE V4

PURPOSE
Catch a developing intraday leader quickly enough to evaluate CE/PE while the move is still developing.

V4 adds to V3:
1. FAST_CE_CANDIDATE / FAST_PE_CANDIDATE state.
2. Complete 5m/10m/15m history guard.
3. Rank acceleration.
4. Price acceleration.
5. Top-20 / Top-10 persistence.
6. Day-range position confirmation.
7. Saved 1-minute price-structure confirmation.
8. Extension/chase guard.
9. First-qualified-signal episode logic: do not wait for maximum score.
10. Correct late-day forward testing: unavailable 15m/30m/60m horizons are N/A, not zero.
11. Forward 5m/15m/30m/60m + MFE/MAE.
12. Target forensics for BDL, CDSL, GVT&D, POWERGRID, POWERINDIA.

SAFETY
- Research only.
- No Dhan calls.
- No scanner/trading file changes.
- No live orders.
- No paper orders.
- Existing 10% option-capital risk rule is untouched.

IMPORTANT DATA LIMIT
market_watch_1m.csv does not provide enough evidence to honestly replay every desired confirmation.
Therefore V4 does NOT invent VWAP, EMA, volume, option spread, option premium momentum, or option liquidity.
Those belong in the next integration layer using actual saved/source data.

OUTPUT
data\leadership_engine_v4\<DAY>\
    v4_fast_candidates.csv
    v4_symbol_summary.csv
    v4_target_forensics.csv
    run_manifest.json
