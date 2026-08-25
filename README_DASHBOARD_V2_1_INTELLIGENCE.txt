APlus Dashboard V2.1 Intelligence Upgrade

Purpose:
Fix the right-hand intelligence panels using the minute-by-minute price history
already stored locally. No Dhan calls are added.

Calculated from saved market_watch_1m.csv:
- 5m / 10m / 15m momentum
- range position
- trend retention
- pullback depth
- recent price-structure ratio
- fresh break
- progressive move
- reacceleration
- earliest technically meaningful movement-start time

Important:
The existing chart-history collector stores price/open/high/low/range data but
does NOT store volume or VWAP fields. Therefore V2.1 deliberately shows VWAP as
N/A when no real VWAP exists instead of incorrectly displaying 0.00.

This is technically honest and avoids fabricating indicators.

Existing scanner, risk, option selection, paper journal and Dhan API code are
untouched.
