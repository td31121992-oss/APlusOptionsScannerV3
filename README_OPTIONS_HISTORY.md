# Historical stock-option data (5 years) for backtesting

Downloaded from Dhan's expired-options ("rolling option") API by `download_expired_options.py`
into `E:\APlusData\expired_options` (override with `APLUS_OPTIONS_HISTORY`).

## What is stored
For each of the 213 F&O stocks, every 30-day window since 2021-07-01, calls and puts, near-month
expiry, strikes ATM-3 ... ATM+3. One gzip-JSON file per request:

    <SYMBOL>/<window start>/<expiry code>_<CE|PE>_<ATM+n>.json.gz     e.g. RELIANCE/2026-09-01/1_CE_ATM+1.json.gz

Each response has 5-minute candles (09:15-15:35, 77 per day): open, high, low, close, volume,
**open interest, implied volatility, spot price and the actual strike**.

The series is *rolling*: at every timestamp the contract is the near-month option whose strike is
`n` steps from the money **at that moment** (`strike` tells you which). That matches how the scanner
picks an option (near-ATM), so backtests can replay entries and exits on real option prices.

## Reading it
```python
from options_history import load_series, coverage
df = load_series("RELIANCE", "CALL", offset=0, start="2025-09-01", end="2025-12-31")
coverage()      # per symbol: windows stored / windows that actually contain data
```

## Running / status
- Scheduled task `APlus_Options_History_Download` runs daily 16:00 and stops at 08:30; it resumes where it
  left off, never calls Dhan during weekday market hours (09:00-15:45), and backs off on rate limits.
- Progress: Control Room "Options history download", or `E:\APlusData\expired_options\_progress.json`,
  or `python download_expired_options.py --plan`.
- Every response is stored, including empty ones, so re-runs never repeat a request.

## Caveats (read before trusting a backtest)
- **Dhan's history is patchy.** Some stock/period windows are empty (seen for RELIANCE in Sep 2022-2024
  but present for Mar 2022 and Sep 2025). Always check `coverage()` and skip empty windows - never treat
  "no data" as "no trade".
- Rolling series are continuous across expiries: the premium jumps when the near month rolls. Handle
  roll days explicitly in any holding-period logic.
- Candle prices are traded prices, not bid/ask: model spread and fees (see `trade_costs.py`).
- Only ATM +/- 3 strikes and near-month expiry are downloaded by default; use
  `--strikes N` and `--expiry-codes 1,2` to widen (more calls, more disk).
