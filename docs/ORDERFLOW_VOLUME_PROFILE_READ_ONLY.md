# Read-only Footprint and Volume Profile

This module is an independent analytics layer. It is not integrated with scanner
eligibility, paper-trade execution, portfolio risk, broker authentication, or order
placement.

## Volume Profile

build_volume_profile(candles) returns estimated POC, VAH/VAL and high-/low-volume
nodes. The initial implementation spreads each OHLCV candle's volume uniformly
across the prices touched by its high-low range. This is explicitly labelled
OHLCV_RANGE_UNIFORM_ESTIMATE and is NOT a true traded-volume-at-price profile.
Use a real trade-at-price feed for production-grade profile values.

## Footprint

analyze_footprint(levels) requires records containing price, bid_volume and
ask_volume. Delta is ask volume minus bid volume. Imbalance is labelled when one
side reaches the configured ratio, and stacked imbalances are contiguous runs of
at least three price levels.

The meaning of bid/ask volumes depends on the upstream feed's aggressor
classification. The function will not synthesize bid/ask volume from OHLCV bars.
If those fields are absent, it returns bid_ask_volume_by_price_unavailable.

## Not included yet

- Live feed adapter or persistent tick capture.
- Time-sequenced CVD/absorption/exhaustion detection.
- Multi-session profile comparisons or dashboard integration.
- Historical trade-by-trade evaluation.

Dhan's historical chart API provides OHLCV candles, which alone do not reconstruct
the full bid/ask volume at each price. Dhan documents separate live market-feed
and market-depth APIs; access, entitlement, packet fields, and rate limits must be
verified before a feed adapter is implemented. This module never places orders.
