"""Chart-pattern shadow tags at entry (recorded on the candidate / trade, never used to allow or block anything).

Runs the same detector as the nightly pattern log (pattern_log.detect_events: 42 candle / structure patterns on the stock's 5-minute candles) on today's completed
candles, and keeps the patterns that FORMED in the last 3 bars (about 15 minutes) - each tagged by whether it points with or against the trade's direction.

    pt_recent         patterns formed on the last 3 bars, each as name:with / name:against / name:neutral   (e.g. "bearish_engulfing:against|doji:neutral")
    pt_with           number of with-direction patterns in the last 3 bars
    pt_against        number of against-direction patterns in the last 3 bars
    pt_last_bar       patterns on the latest completed bar only
    pt_reversal_against   True when a classic reversal pattern against us formed in the last 3 bars (call: bearish engulfing / shooting star / dark cloud / evening star /
                          bearish harami / double top; put: the mirror)

Works from 4 bars of data (the first 20 minutes of the session), so it can speak about the early entries too; structure patterns that need a longer history simply do not fire.
"""

from __future__ import annotations

from typing import Any, Sequence

BEAR_REVERSAL = {"bearish_engulfing", "shooting_star", "dark_cloud_cover", "evening_star", "bearish_harami", "double_top"}
BULL_REVERSAL = {"bullish_engulfing", "hammer", "piercing_line", "morning_star", "bullish_harami", "double_bottom"}
RECENT_BARS = 3


def pattern_tags(candles: Sequence[Any], direction: str) -> dict[str, Any]:
    try:
        cs = [c for c in candles if getattr(c, "close", 0)]
        if len(cs) < 4:
            return {}
        import pattern_log

        data = {"timestamp": [int(c.timestamp.timestamp()) for c in cs], "open": [float(c.open) for c in cs], "high": [float(c.high) for c in cs],
                "low": [float(c.low) for c in cs], "close": [float(c.close) for c in cs], "volume": [float(c.volume or 0) for c in cs]}
        events = pattern_log.detect_events(data, min_bars=4)
        mins = sorted({e["minute"] for e in events} | {pattern_log._minutes(data["timestamp"][-1])})
        last = pattern_log._minutes(data["timestamp"][-1])
        cutoff = last - 5 * (RECENT_BARS - 1)
        bull = str(direction).upper() == "BULLISH"
        sign = 1 if bull else -1
        recent = [e for e in events if e["minute"] >= cutoff]
        out: dict[str, Any] = {}

        def rel(e: dict[str, Any]) -> str:
            return "neutral" if not e["side"] else ("with" if e["side"] == sign else "against")

        out["pt_recent"] = "|".join(sorted(f"{e['pattern']}:{rel(e)}" for e in recent))
        out["pt_with"] = sum(1 for e in recent if rel(e) == "with")
        out["pt_against"] = sum(1 for e in recent if rel(e) == "against")
        out["pt_last_bar"] = "|".join(sorted(f"{e['pattern']}:{rel(e)}" for e in events if e["minute"] == last))
        bad = BEAR_REVERSAL if bull else BULL_REVERSAL
        out["pt_reversal_against"] = any(e["pattern"] in bad for e in recent)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
