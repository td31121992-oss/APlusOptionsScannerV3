"""Stock-structure stop levels recorded at entry for two SHADOW exits (never used for a real exit).

Idea (16 Oct 2026, TECHM): the option's own -20% stop sits inside normal noise, while the stock was still above its breakout. These shadows
ask "what if the trade were only given up when the STOCK breaks its structure?" - the option stop stays the real exit.

    sk_orb_level   calls: low of the opening range (09:15-09:30); puts: high of the opening range
    sk_sw_level    calls: lowest low of the last 6 completed 5-minute candles (30 min swing); puts: highest high of them
The journal records the shadow exits `skorb` and `sksw`: the first time the stock trades beyond the level against us on two readings in a row,
at that moment's option price (see paper_trade_journal.record_stock_response). Trades that never trigger exit with the real exit.
"""

from __future__ import annotations

from typing import Any, Sequence

OPENING_RANGE_END_MIN = 9 * 60 + 30
SWING_BARS = 6
MIN_BARS = 4


def _g(c: Any, name: str) -> float:
    try:
        return float(c[name] if isinstance(c, dict) else getattr(c, name))
    except (KeyError, AttributeError, TypeError, ValueError):
        return 0.0


def _minute(c: Any) -> int | None:
    try:
        ts = c["timestamp"] if isinstance(c, dict) else c.timestamp
        return ts.hour * 60 + ts.minute
    except (KeyError, AttributeError, TypeError):
        return None


def entry_levels(day_candles: Sequence[Any], direction: str) -> dict[str, Any]:
    try:
        cs = [c for c in day_candles if _g(c, "close") > 0]
        if len(cs) < MIN_BARS:
            return {}
        bull = str(direction).upper() == "BULLISH"
        opening = [c for c in cs if (_minute(c) is not None and _minute(c) < OPENING_RANGE_END_MIN)] or cs[:3]
        swing = cs[-SWING_BARS:]
        if bull:
            orb = min(_g(c, "low") for c in opening)
            sw = min(_g(c, "low") for c in swing)
        else:
            orb = max(_g(c, "high") for c in opening)
            sw = max(_g(c, "high") for c in swing)
        return {"sk_orb_level": round(orb, 2), "sk_sw_level": round(sw, 2)}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


def breached(price: float, level: float, option_type: str) -> bool:
    """True when the stock trades beyond the level against the position (calls: at/below, puts: at/above)."""
    if price <= 0 or level <= 0:
        return False
    return price <= level if str(option_type).upper() == "CE" else price >= level
