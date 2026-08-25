APLUS LEADERSHIP ENGINE V6

Purpose
-------
Use the exact V5 signal minute and reconstruct chart structure from persisted
1-minute LTP history before allowing the candidate to remain a fast CE/PE setup.

What V6 evaluates
-----------------
- sampled 5-minute candle body quality
- close location inside sampled candle
- higher-high / higher-low (or lower-high / lower-low) proxy
- breakout of recent sampled swing
- breakout retention
- rejection wick ratio
- consecutive directional sampled candles
- extension / possible blow-off move
- pause-retain path for strong top-10 leaders

Important data honesty
----------------------
The project currently persists 1-minute LTP observations in market_watch_1m.csv.
V6 groups those observations into 5-minute sampled OHLC.

These are NOT exchange-accurate candles.
They are a faithful reconstruction from the saved LTP observations only.

V6 does NOT fabricate:
- exchange volume
- VWAP history
- EMA history
- ADX history
- true exchange OHLC
- option premium history

Safety
------
READ ONLY
ZERO Dhan calls
NO production scanner modifications
NO paper orders
NO live orders
