"""Order-block detector on 5-minute candles (shadow tagging only - it never blocks or changes a trade).

Bullish order block: the last down candle (within 3 bars) before a strong up candle (body >= impulse_atr x ATR) that
also closes above the previous `lookback` highs. Bearish is the mirror image. The block stays "fresh" while no
candle has closed beyond its far side. State for the latest bar:
  IN_FRESH_OB  - last close is inside the zone (the retest the strategy waits for)
  ABOVE_OB     - (bullish) price is above a fresh zone: not retested yet / BELOW_OB for bearish
  NONE         - no fresh block in the last `max_age` bars, or too little data
Used to tag every paper trade (ob_shadow) so we can compare outcomes by tag later.
"""

from __future__ import annotations

from typing import Any, Sequence


def _atr(candles: Sequence[Any], period: int = 14) -> list[float]:
    out: list[float] = []
    trs: list[float] = []
    prev_close = None
    for c in candles:
        tr = max(c.high - c.low, abs(c.high - prev_close) if prev_close is not None else 0.0,
                 abs(c.low - prev_close) if prev_close is not None else 0.0)
        trs.append(tr)
        out.append(sum(trs[-period:]) / len(trs[-period:]) if len(trs) >= period else 0.0)
        prev_close = c.close
    return out


def order_block_state(candles: Sequence[Any], direction: str, *, lookback: int = 10, impulse_atr: float = 1.5,
                      max_age: int = 36) -> dict[str, Any]:
    none = {"state": "NONE", "zone_low": 0.0, "zone_high": 0.0, "age_bars": 0}
    n = len(candles)
    if n < lookback + 6:
        return none
    bull = str(direction).upper() == "BULLISH"
    atr = _atr(candles)
    last = candles[-1]
    start = max(lookback, n - max_age)
    for i in range(n - 1, start - 1, -1):                       # newest impulse first
        c = candles[i]
        if atr[i] <= 0:
            continue
        body = (c.close - c.open) if bull else (c.open - c.close)
        if body < impulse_atr * atr[i]:
            continue
        window = candles[i - lookback:i]
        if bull and not c.close > max(x.high for x in window):
            continue
        if (not bull) and not c.close < min(x.low for x in window):
            continue
        block = None
        for j in range(i - 1, max(i - 4, 0), -1):
            if (bull and candles[j].close < candles[j].open) or ((not bull) and candles[j].close > candles[j].open):
                block = candles[j]
                break
        if block is None:
            continue
        zone_low, zone_high = block.low, block.high
        after = candles[i + 1:]
        violated = any((x.close < zone_low) if bull else (x.close > zone_high) for x in after)
        if violated:
            continue
        if zone_low <= last.close <= zone_high:
            state = "IN_FRESH_OB"
        elif bull and last.close > zone_high:
            state = "ABOVE_OB"
        elif (not bull) and last.close < zone_low:
            state = "BELOW_OB"
        else:
            continue
        return {"state": state, "zone_low": round(zone_low, 4), "zone_high": round(zone_high, 4), "age_bars": n - 1 - i}
    return none
