APlus Leadership Engine V3

Research-only full-market replay.

Tests:
- 5m / 10m / 15m rank acceleration
- 5m / 10m / 15m price acceleration
- top-10 / top-20 leadership
- 5-minute persistence
- range-position confirmation
- complete-window guard: no fake 5-minute acceleration before enough history exists
- forward 5m / 15m / 30m / 60m performance
- 60m MFE / MAE

No production scanner files are modified.
No Dhan API calls are made.

Note: volume/VWAP/EMA/previous-day-high features are not fabricated when the saved chart-history dataset does not contain them. They should be layered in only after this rank/price/persistence core is validated.
