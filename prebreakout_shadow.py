"""Research-only pre-breakout watch labels from stored intraday OHLCV.

This module is deliberately not imported by the scanner, dashboard, or order
path. Candidate labels use only the current and prior candles; outcome labels
are calculated separately from later candles for offline evaluation.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def candidates_for_day(
    symbols: Mapping[str, Mapping[str, Any]],
    *,
    max_level_distance_pct: float = 0.60,
    min_volume_multiple: float = 1.30,
    require_complete_volume_window: bool = False,
) -> list[dict[str, Any]]:
    """Return first watch-only setup per symbol/side before a PDH/PDL/OR break.

    The opening range is the first three stored bars. A candidate must be
    within the configured distance of an unbroken level, show directional
    close location and close progression, and have volume above the median of
    the preceding three bars. These are fixed research parameters, not live
    entry rules or recommendations.
    """
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_symbol, bars in symbols.items():
        symbol = str(raw_symbol).strip().upper()
        minutes = bars.get("minute") or []
        opens, highs, lows, closes, volumes = (bars.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
        n = min(map(len, (minutes, opens, highs, lows, closes, volumes)))
        if not symbol or n < 4:
            continue
        pdh, pdl = _finite(bars.get("pdh")), _finite(bars.get("pdl"))
        orh = max((_finite(v) or -math.inf for v in highs[:3]), default=-math.inf)
        orl = min((_finite(v) or math.inf for v in lows[:3]), default=math.inf)
        resistance = [v for v in (pdh, orh) if v is not None and math.isfinite(v) and v > 0]
        support = [v for v in (pdl, orl) if v is not None and math.isfinite(v) and v > 0]

        for i in range(3, n):
            minute = int(minutes[i])
            if minute > 14 * 60 + 30:
                continue
            o, h, l, c, v = (_finite(x) for x in (opens[i], highs[i], lows[i], closes[i], volumes[i]))
            prev_close = _finite(closes[i - 1])
            prior_volumes = [_finite(x) for x in volumes[max(0, i - 3):i]]
            prior_volumes = [x for x in prior_volumes if x is not None and x > 0]
            if None in (o, h, l, c, v, prev_close) or h < l or c <= 0 or l <= 0 or not prior_volumes:
                continue
            if require_complete_volume_window:
                observed = [_finite(x) for x in volumes[i - 3:i]]
                if len(observed) != 3 or any(x is None or x <= 0 for x in observed):
                    continue
            median_volume = sorted(prior_volumes)[len(prior_volumes) // 2]
            if median_volume <= 0 or v < min_volume_multiple * median_volume:
                continue
            candle_range = h - l
            close_location = (c - l) / candle_range if candle_range > 0 else 0.5

            for side, levels, directional, location_ok in (
                ("BULLISH", resistance, c > prev_close, close_location >= 0.70),
                ("BEARISH", support, c < prev_close, close_location <= 0.30),
            ):
                key = (symbol, side)
                if key in found or not directional or not location_ok:
                    continue
                if side == "BULLISH":
                    unbroken = [level for level in levels if c < level and h < level]
                else:
                    unbroken = [level for level in levels if c > level and l > level]
                if not unbroken:
                    continue
                level = min(unbroken) if side == "BULLISH" else max(unbroken)
                distance = ((level - c) if side == "BULLISH" else (c - level)) / c * 100.0
                if 0 < distance <= max_level_distance_pct:
                    found[key] = {
                        "symbol": symbol,
                        "side": side,
                        "minute": minute,
                        "close": c,
                        "level": level,
                        "level_distance_pct": distance,
                        "volume_multiple": v / median_volume,
                        "close_location": close_location,
                    }
    return sorted(found.values(), key=lambda x: (x["minute"], x["symbol"], x["side"]))


def evaluate_candidate(candidate: Mapping[str, Any], bars: Mapping[str, Any], *, confirm_bars: int = 6, outcome_bars: int = 12) -> dict[str, Any]:
    """Label later level confirmation and underlying follow-through (no option P&L)."""
    minutes = bars.get("minute") or []
    highs, lows, closes = (bars.get(k) or [] for k in ("high", "low", "close"))
    side, level, signal_minute = candidate.get("side"), _finite(candidate.get("level")), int(candidate.get("minute", -1))
    if level is None:
        return {"confirmed": False, "confirmation_minute": None, "forward_best_pct": None, "forward_worst_pct": None}
    signal_indices = [i for i, m in enumerate(minutes) if int(m) == signal_minute]
    if not signal_indices:
        return {"confirmed": False, "confirmation_minute": None, "forward_best_pct": None, "forward_worst_pct": None}
    i = signal_indices[-1]
    confirmation = None
    for j in range(i + 1, min(len(minutes), i + 1 + confirm_bars)):
        h, l, c = (_finite(highs[j]), _finite(lows[j]), _finite(closes[j]))
        if None in (h, l, c):
            continue
        if (side == "BULLISH" and h >= level and c > level) or (side == "BEARISH" and l <= level and c < level):
            confirmation = j
            break
    if confirmation is None:
        return {"confirmed": False, "confirmation_minute": None, "forward_best_pct": None, "forward_worst_pct": None}
    entry = _finite(closes[confirmation])
    if entry is None or entry <= 0:
        return {"confirmed": True, "confirmation_minute": int(minutes[confirmation]), "forward_best_pct": None, "forward_worst_pct": None}
    end = min(len(minutes), confirmation + 1 + outcome_bars)
    future_highs = [_finite(x) for x in highs[confirmation + 1:end]]
    future_lows = [_finite(x) for x in lows[confirmation + 1:end]]
    future_highs = [x for x in future_highs if x is not None]
    future_lows = [x for x in future_lows if x is not None]
    if not future_highs or not future_lows:
        best = worst = None
    elif side == "BULLISH":
        best = (max(future_highs) / entry - 1) * 100.0
        worst = (min(future_lows) / entry - 1) * 100.0
    else:
        best = (1 - min(future_lows) / entry) * 100.0
        worst = (1 - max(future_highs) / entry) * 100.0
    return {
        "confirmed": True,
        "confirmation_minute": int(minutes[confirmation]),
        "forward_best_pct": best,
        "forward_worst_pct": worst,
    }

