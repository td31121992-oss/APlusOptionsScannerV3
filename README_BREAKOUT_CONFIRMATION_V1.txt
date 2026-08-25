APlus Breakout Confirmation V1

Fixes TWO verified bare-touch paths:
1) fresh 15m/30m breakout
2) continuation breakout after pullback

Confirmed-break rule:
- prior completed candles define level
- latest completed candle must close beyond level
- clearance = max(0.08% of level, 10% median reference candle range)
- live price must still hold beyond 25% of that clearance

Also starts a ZERO-Dhan local evidence collector that aggregates 5-second
Market Watch snapshots into 1-minute OHLC + volume delta + average price for
future backtesting.

Run:
install_breakout_confirmation_v1_ONE_GO.bat
