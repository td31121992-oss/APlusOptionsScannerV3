"""Stock-trend shadow tags at entry (SHADOW / RESEARCH - never blocks or changes a trade).

Records, for every new paper trade, the same trend gauge the trade page shows (see stock_trend.py):

    tr_5m_score / tr_15m_score / tr_daily_score    -1 (all bearish) .. +1 (all bullish), signed in the STOCK's direction
    tr_5m_bull / tr_5m_neu / tr_5m_bear            indicator votes on the 5-minute timeframe (same for 15m and daily)
    tr_adx_5m, tr_rsi_5m                           the two numbers worth tracking on their own
    tr_aligned_5m / tr_aligned_15m / tr_aligned_daily   True when that timeframe's score points the way of the TRADE (|score| >= 0.2)
    tr_all_aligned                                 True when 5M and 15M are both aligned
    tr_scans_for / tr_scans_against                number of intraday scans that favour / oppose the trade (breakouts, open=low, ...)

One extra intraday request (about 9 sessions of 5-minute candles, cached for 45 s) and one daily-history request (cached for an
hour) per new entry, both with short timeouts; any failure just means no tags.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ALIGN = 0.2


def tags_from_trend(trend: dict[str, Any], direction: str) -> dict[str, Any]:
    if not trend:
        return {}
    sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
    out: dict[str, Any] = {}
    for key, short in (("5M", "5m"), ("15M", "15m"), ("DAILY", "daily")):
        t = trend.get(key)
        if not t or not t.get("table") and not (t.get("bullish") or t.get("bearish") or t.get("neutral")):
            continue
        score = float(t.get("score") or 0.0)
        out[f"tr_{short}_score"] = round(score, 3)
        out[f"tr_{short}_bull"], out[f"tr_{short}_neu"], out[f"tr_{short}_bear"] = t.get("bullish", 0), t.get("neutral", 0), t.get("bearish", 0)
        out[f"tr_aligned_{short}"] = bool(sign * score >= ALIGN)
        for row in t.get("table") or []:
            if short == "5m" and row.get("name") == "ADX":
                out["tr_adx_5m"] = row.get("value")
            if short == "5m" and row.get("name") == "RSI":
                out["tr_rsi_5m"] = row.get("value")
    if "tr_aligned_5m" in out and "tr_aligned_15m" in out:
        out["tr_all_aligned"] = bool(out["tr_aligned_5m"] and out["tr_aligned_15m"])
    scans = trend.get("scans") or []
    want = "bull" if sign > 0 else "bear"
    out["tr_scans_for"] = sum(1 for s in scans if s.get("tone") == want)
    out["tr_scans_against"] = sum(1 for s in scans if s.get("tone") and s.get("tone") != want)
    names_for = [s.get("text", "") for s in scans if s.get("tone") == want and s.get("text")]
    names_against = [s.get("text", "") for s in scans if s.get("tone") and s.get("tone") != want and s.get("text")]
    out["tr_scans_names"] = "|".join(names_for)
    out["tr_scans_against_names"] = "|".join(names_against)
    # the two groups the review tracks on their own: the open at the day's extreme, and a multi-day level already broken
    out["tr_open_ext"] = any(n.startswith("Open = ") for n in names_for)
    out["tr_multi_day"] = any(("Days Breakout" in n or "Days Breakdown" in n) for n in names_for)
    return out


def entry_trend(symbol: str, direction: str, day: str, root: Path) -> dict[str, Any]:
    """Fetch the history (short timeouts) and return the tags; {} on any problem."""
    try:
        import stock_trend
        import trade_chart
        from order_book_recorder import _universe

        if not trade_chart._UNIVERSE:
            trade_chart._UNIVERSE.update(_universe())
        sid = trade_chart._UNIVERSE.get(symbol)
        if not sid:
            return {}
        five, start = trade_chart._five_history(sid, day, timeout=10)
        daily = trade_chart._daily_history(sid, day, timeout=10)
        try:
            ind = json.loads((Path(root) / "data" / "reports" / "daily_indicators.json").read_text(encoding="utf-8")).get("symbols", {}).get(symbol)
        except (OSError, ValueError):
            ind = None
        prev_close = daily["c"][-1] if daily.get("c") else float((ind or {}).get("last_close") or 0)
        trend = stock_trend.build(five, start, daily, ind, prev_close, str(direction).upper() == "BULLISH")
        return tags_from_trend(trend, direction)
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
