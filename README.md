# APlus Stock–Option Response Shadow v1

## Purpose
Measure the actual option premium response to the underlying stock move after a paper entry. It explicitly distinguishes:
- percentage move from underlying entry price;
- stock's day-reference move at entry and now (if prior close/reference is supplied);
- option premium change in rupees and percent from option entry;
- elapsed time;
- favorable/adverse direction for CE/PE;
- cases where stock moves favorably but the option premium fails to respond.

## Safety
- SHADOW ONLY. No order placement, no close/exit action, no mutation of the trade.
- It does not infer option price from stock movement. Both prices must be observed from quotes.
- It cannot prove theta decay by itself. IV, delta/gamma, expiry, moneyness, spread, stale quotes and liquidity can also affect premium.
- Keep live trading disabled; do not change existing exits or scanner rules for this feature.

## Expected inputs
`evaluate_response(trade, underlying_price, option_price, quote_time, day_reference_price=None)`

Trade fields:
- `paper_trade_id` (or `trade_id`)
- `side`: CE/CALL or PE/PUT
- `underlying_entry_price` (or `underlying_entry`)
- `option_entry_price` (or `entry_price`)
- `entry_time` (ISO-8601; optional for elapsed time)
- `day_reference_price` / `underlying_day_reference` (optional, usually previous close)

Call it for every fresh underlying/option quote pair for each open paper trade. Use the same quote timestamp where possible. Reject or flag stale/invalid quotes in the caller; this module marks the mode and returns calculations only.

## Install safely
1. Extract this folder to a temporary location first.
2. Copy `stock_option_response_shadow.py` and its test into the project root:
   `C:\\Users\\Aplus\\Desktop\\APlusOptionsScannerV3`
3. Do not overwrite existing files; if either filename already exists, stop and compare.
4. Run:
   `python -m unittest -v test_stock_option_response_shadow.py`
5. Integration into the journal/dashboard is deliberately not automatic. The user's local journal/dashboard have uncommitted changes; the next integration patch should be based on the exact local quote-update and dashboard rendering sections.

## Example
At entry stock ₹1,000 and option ₹100. Later stock ₹1,015 and option ₹112:
- stock from entry: +1.5%;
- option from entry: +12%;
- option premium gain: ₹12 per unit.
This is an observed relationship for that trade, not a universal multiplier.
