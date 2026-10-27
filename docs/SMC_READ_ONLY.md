# Read-only Smart Money Concepts analysis

smc_readonly.py is an independent, read-only feature extractor for OHLC candles. It is not connected to the trading engine and must not alter entry eligibility, paper-trade execution, risk limits, broker authentication, or live-order authority.

## Features

- Confirmed swing highs/lows and simple HH/LH/EQH and HL/LL/EQL labels.
- Basic bullish/bearish structure classification.
- Close-through confirmed swing levels as BOS candidates; opposing break is labelled a CHoCH candidate.
- Simple wick-and-close liquidity sweep heuristics.
- Three-candle bullish/bearish fair-value-gap (FVG) heuristic.
- ATR-normalized five-bar directional velocity and candle displacement.
- Separate bullish/bearish heuristic scores from 0 to 100, with transparent component rules.

## Use

Call analyze_smc(candles) with chronological dictionaries containing open, high, low, and close; volume is optional. The result contains analysis_mode: READ_ONLY and trade_decision: null. Insufficient or malformed data is reported explicitly.

## Important limitations

- SMC terms are interpretations of price action; these features do not establish that institutional orders occurred.
- Scores are heuristic feature scores, not probabilities, expected returns, or entry recommendations.
- Pivot labels use right-side confirmation bars and therefore arrive with a delay. Do not backtest a pivot as known before confirmation.
- This initial module is not yet integrated into the dashboard, does not calculate order blocks or premium/discount dealing ranges, and has no multi-timeframe alignment. Those require separate definitions and tests.
- Validate on historical and out-of-sample data before considering any future use in trade selection.
