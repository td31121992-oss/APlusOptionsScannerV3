"""Chart-engineering features as plain numbers (no discretionary rules), for the data-science model and the dashboard.

All functions take a price series up to and INCLUDING the decision bar - never future bars - and return floats.
`side` is +1 for a bullish view (call) and -1 for a bearish view (put); "directional" values are multiplied by side so
that a positive number always means "price moved the way the trade needs".
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def pct_change(series: Sequence[float], bars: int) -> float:
    s = np.asarray(series, dtype=float)
    if len(s) <= bars or s[-1 - bars] <= 0:
        return 0.0
    return float(s[-1] / s[-1 - bars] - 1.0) * 100.0


def directional(value: float, side: int) -> float:
    return float(value) * (1 if side >= 0 else -1)


def range_position(series: Sequence[float]) -> float:
    """0 = at the day low so far, 1 = at the day high so far."""
    s = np.asarray(series, dtype=float)
    lo, hi = float(s.min()), float(s.max())
    return float((s[-1] - lo) / (hi - lo)) if hi > lo else 0.5


def distance_from_extreme_pct(series: Sequence[float], side: int) -> float:
    """How far (in %) price still is from the extreme in the trade's direction: the day high for calls, the day low for puts."""
    s = np.asarray(series, dtype=float)
    if s[-1] <= 0:
        return 0.0
    extreme = s.max() if side >= 0 else s.min()
    return float(abs(extreme - s[-1]) / s[-1]) * 100.0


def realized_volatility_pct(series: Sequence[float], bars: int = 12) -> float:
    s = np.asarray(series, dtype=float)[-(bars + 1):]
    if len(s) < 3:
        return 0.0
    r = np.diff(s) / s[:-1]
    return float(np.std(r)) * 100.0


def opening_range_status(series: Sequence[float], side: int, bars: int = 3) -> float:
    """+1 if price is beyond the opening range in the trade's direction, -1 if beyond it against, 0 inside."""
    s = np.asarray(series, dtype=float)
    if len(s) <= bars:
        return 0.0
    hi, lo = float(s[:bars].max()), float(s[:bars].min())
    last = float(s[-1])
    state = 1.0 if last > hi else (-1.0 if last < lo else 0.0)
    return state * (1 if side >= 0 else -1)


def trend_slope_pct_per_bar(series: Sequence[float], bars: int = 12) -> float:
    s = np.asarray(series, dtype=float)[-bars:]
    if len(s) < 4 or s[0] <= 0:
        return 0.0
    x = np.arange(len(s), dtype=float)
    slope = np.polyfit(x, s, 1)[0]
    return float(slope / s[0]) * 100.0


def trend_efficiency(series: Sequence[float], bars: int = 12) -> float:
    """Net move divided by total path length (1 = straight line, 0 = pure chop)."""
    s = np.asarray(series, dtype=float)[-(bars + 1):]
    if len(s) < 3:
        return 0.0
    path = float(np.abs(np.diff(s)).sum())
    return float(abs(s[-1] - s[0]) / path) if path > 0 else 0.0


def feature_vector(spot: Sequence[float], side: int) -> dict[str, float]:
    """The standard chart-feature set for the latest bar of an intraday spot series."""
    return {
        "d_ret_open": directional(pct_change(spot, len(spot) - 1), side),
        "d_ret_3": directional(pct_change(spot, 3), side),
        "d_ret_6": directional(pct_change(spot, 6), side),
        "d_ret_12": directional(pct_change(spot, 12), side),
        "range_pos_dir": range_position(spot) if side >= 0 else 1.0 - range_position(spot),
        "dist_extreme_pct": distance_from_extreme_pct(spot, side),
        "vol_12": realized_volatility_pct(spot, 12),
        "or_status": opening_range_status(spot, side),
        "d_slope_12": directional(trend_slope_pct_per_bar(spot, 12), side),
        "efficiency_12": trend_efficiency(spot, 12),
    }
