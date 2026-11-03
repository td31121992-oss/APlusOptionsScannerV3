"""R1 / S1 break-time tags at entry (SHADOW ONLY - recorded on the trade, never used to allow or block anything).

For a call the level is R1, for a put it is S1 (the scanner's own classic pivots from the previous session). From today's completed 5-minute candles:

    pv_level            the level (R1 for calls, S1 for puts)
    pv_break_time       time of the first 5-minute CLOSE beyond the level today, HH:MM, blank if there has been none
    pv_since_break_min  minutes from that break candle to the entry
    pv_gap              True when the very first candle already closed beyond the level (a gap, not a break during the day)
    pv_past_level_pct   how far the stock is past the level now, in the trade's direction (negative = still on the wrong side of it)
    pv_break_dist_pct   how far past the level the break candle closed

1-15 Oct replay of every stock: S1 breaks between 10:00 and 12:30 held up best (-1% first only 14-17%), R1 breaks showed no edge (see the break report in the chat history /
pivot_review.md). This tag lets the nightly review check the same thing on the trades themselves.
"""

from __future__ import annotations

from typing import Any, Sequence


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


def break_tags(day_candles: Sequence[Any], direction: str, r1: Any, s1: Any, ltp: Any, entry_minute: int | None) -> dict[str, Any]:
    try:
        bull = str(direction).upper() == "BULLISH"
        level = float(r1 if bull else s1)
        if level <= 0:
            return {}
        sg = 1 if bull else -1
        cs = [c for c in day_candles if _g(c, "close") > 0]
        out: dict[str, Any] = {"pv_level": round(level, 2)}
        first = next((i for i, c in enumerate(cs) if sg * (_g(c, "close") - level) >= 0), None)
        if first is not None:
            m = _minute(cs[first])
            if m is not None:
                out["pv_break_time"] = f"{m // 60:02d}:{m % 60:02d}"
                if entry_minute is not None:
                    out["pv_since_break_min"] = max(0, entry_minute - m)
            out["pv_gap"] = bool(first == 0)
            out["pv_break_dist_pct"] = round(sg * (_g(cs[first], "close") / level - 1.0) * 100.0, 3)
        else:
            out["pv_break_time"] = ""
            out["pv_gap"] = False
        px = float(ltp) if ltp not in (None, "") else (_g(cs[-1], "close") if cs else 0.0)
        if px > 0:
            out["pv_past_level_pct"] = round(sg * (px / level - 1.0) * 100.0, 3)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
