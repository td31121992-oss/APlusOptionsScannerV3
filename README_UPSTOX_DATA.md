# Upstox as a free market-data source (Dhan stays the default and the fallback)

Nothing changes unless you set an environment variable. Trading orders are not involved: this is quotes and candles only.

## Switches
| Variable | Effect |
|---|---|
| *(nothing set)* | Dhan for everything, exactly as before |
| `APLUS_UPSTOX_SHADOW=1` | Trade on Dhan data; each minute the same quote request also goes to Upstox in the background and the difference is written to `data/upstox_shadow/<date>.csv` (matched count, median / max price difference, previous-close difference, volume ratio, seconds taken by each). Upstox data is never used for a decision. |
| `APLUS_DATA_PROVIDER=UPSTOX` | Quotes and candles from Upstox first. A failed, empty or incomplete (< 90% of instruments) answer, or an exhausted request budget, falls back to Dhan **for that call**. Option chain, expiries, funds and positions always stay on Dhan. |

Token: `UPSTOX_ANALYTICS_TOKEN` in `.env` (free, read-only, generated in the Upstox developer console). Candle endpoints work
without a token; quote endpoints need it. Without the token the code stays on Dhan.

## What was verified (14 Oct 2026, no token needed)
* 213 of 213 F&O stocks map: Dhan security id equals the Upstox exchange token. Options map the same way (`NSE_FO|<token>`).
* 5-minute candles match Dhan within ticks, no time shift; the 09:15 candle has the correct open and low; Upstox returns all 75
  candles of a day (Dhan omits the last three).
* The client returns Dhan-shaped data (`get_market_quotes`, `get_intraday_candles`), so the scanner code is unchanged.

## Not verified yet (needs the token and market hours)
* Live quote completeness and speed for ~213 stocks + open options, and whether `ohlc.close` is yesterday's close during the
  session (the client falls back to `last_price - net_change` when `close` equals the last price).
* Behaviour under the Upstox limits (50/s, 500/min, 2000 per 30 min). The client keeps a budget of 20/s, 400/min and 1700 per
  30 min and raises so the hybrid falls back to Dhan instead of getting blocked.

## Rollout
1. Add `UPSTOX_ANALYTICS_TOKEN`, set `APLUS_UPSTOX_SHADOW=1`, restart the scanner. Read `data/upstox_shadow/*.csv` for a few sessions.
2. If differences are tiny and `missing` stays near 0, set `APLUS_DATA_PROVIDER=UPSTOX` (Dhan remains the fallback).
3. Roll back by clearing the variable; the scanner returns to Dhan at its next start.
