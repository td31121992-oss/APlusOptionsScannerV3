"""Additional bullish / bearish chart patterns for the pattern outcome log (research only - none of this trades).

Every function works on a 5-minute OHLCV DataFrame (columns open, high, low, close, volume, plus vwap/ema9/ema20 from
candle_chart_patterns.add_chart_structure) and flags the bar on which the pattern is COMPLETE (uses only that bar and earlier bars).

Included: morning / evening star, piercing line / dark cloud cover, three white soldiers / three black crows, bullish / bearish
harami, tweezer bottom / top, inverted hammer after a fall, hanging man after a rise, dragonfly / gravestone doji, VWAP reclaim /
loss, EMA 9/20 cross up / down, double bottom / double top (neckline break), bull / bear flag (break of the pause after a sharp pole).

Not included (too subjective to code honestly without false signals): head-and-shoulders, cup-and-handle, triangles, wedges. They can
be added later once the simple ones show whether pattern recording is worth extending.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EXTRA_SIDES: dict[str, int] = {
    "morning_star": 1, "evening_star": -1, "piercing_line": 1, "dark_cloud_cover": -1,
    "three_white_soldiers": 1, "three_black_crows": -1, "bullish_harami": 1, "bearish_harami": -1,
    "tweezer_bottom": 1, "tweezer_top": -1, "inverted_hammer": 1, "hanging_man": -1,
    "dragonfly_doji": 1, "gravestone_doji": -1, "vwap_reclaim": 1, "vwap_loss": -1,
    "ema_cross_up": 1, "ema_cross_down": -1, "double_bottom": 1, "double_top": -1, "bull_flag": 1, "bear_flag": -1,
}


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _rng(df: pd.DataFrame) -> pd.Series:
    return (df["high"] - df["low"]).replace(0, np.nan)


def _swing(df: pd.DataFrame, col: str, high: bool, k: int = 2) -> list[int]:
    """Indices of confirmed swing highs/lows (higher/lower than k bars each side). Confirmed k bars late, which is how it is used."""
    vals = df[col].to_numpy(dtype=float)
    out = []
    for i in range(k, len(vals) - k):
        window = vals[i - k:i + k + 1]
        if (high and vals[i] == window.max() and (window == vals[i]).sum() == 1) or \
           ((not high) and vals[i] == window.min() and (window == vals[i]).sum() == 1):
            out.append(i)
    return out


def extra_flags(df: pd.DataFrame) -> dict[str, pd.Series]:
    n = len(df)
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body, rng = _body(df), _rng(df)
    ratio = (body / rng).fillna(0)
    bull, bear = c > o, c < o
    po, pc, ph, pl = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    pbull, pbear = bull.shift(1, fill_value=False), bear.shift(1, fill_value=False)
    pratio = ratio.shift(1).fillna(0)
    out: dict[str, pd.Series] = {}

    big_bear2 = bear.shift(2, fill_value=False) & (ratio.shift(2).fillna(0) >= 0.5)
    big_bull2 = bull.shift(2, fill_value=False) & (ratio.shift(2).fillna(0) >= 0.5)
    mid2 = (o.shift(2) + c.shift(2)) / 2
    small1 = pratio <= 0.3
    out["morning_star"] = big_bear2 & small1 & bull & (c > mid2)
    out["evening_star"] = big_bull2 & small1 & bear & (c < mid2)

    mid1 = (po + pc) / 2
    out["piercing_line"] = pbear & (pratio >= 0.5) & bull & (o <= pc) & (c > mid1) & (c < po)
    out["dark_cloud_cover"] = pbull & (pratio >= 0.5) & bear & (o >= pc) & (c < mid1) & (c > po)

    r = (ratio >= 0.5)
    out["three_white_soldiers"] = (bull & bull.shift(1, fill_value=False) & bull.shift(2, fill_value=False) & r
                                   & r.shift(1, fill_value=False) & r.shift(2, fill_value=False)
                                   & (c > pc) & (pc > c.shift(2)))
    out["three_black_crows"] = (bear & bear.shift(1, fill_value=False) & bear.shift(2, fill_value=False) & r
                                & r.shift(1, fill_value=False) & r.shift(2, fill_value=False)
                                & (c < pc) & (pc < c.shift(2)))

    inside_body = (np.maximum(o, c) <= np.maximum(po, pc)) & (np.minimum(o, c) >= np.minimum(po, pc))
    out["bullish_harami"] = pbear & (pratio >= 0.5) & bull & inside_body
    out["bearish_harami"] = pbull & (pratio >= 0.5) & bear & inside_body

    tol = (c.abs() * 0.0005)
    out["tweezer_bottom"] = pbear & bull & ((l - pl).abs() <= tol)
    out["tweezer_top"] = pbull & bear & ((h - ph).abs() <= tol)

    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    fell = (c.shift(1) < c.shift(2)) & (c.shift(2) < c.shift(3))
    rose = (c.shift(1) > c.shift(2)) & (c.shift(2) > c.shift(3))
    out["inverted_hammer"] = fell & (upper >= body * 2) & (lower <= body * 0.8) & (ratio <= 0.5)
    out["hanging_man"] = rose & (lower >= body * 2) & (upper <= body * 0.8) & (ratio <= 0.5)

    doji = ratio <= 0.10
    out["dragonfly_doji"] = doji & (lower >= rng * 0.6) & (upper <= rng * 0.15)
    out["gravestone_doji"] = doji & (upper >= rng * 0.6) & (lower <= rng * 0.15)

    vwap = df["vwap"]
    out["vwap_reclaim"] = (c > vwap) & (c.shift(1) <= vwap.shift(1))
    out["vwap_loss"] = (c < vwap) & (c.shift(1) >= vwap.shift(1))
    e9, e20 = df["ema9"], df["ema20"]
    out["ema_cross_up"] = (e9 > e20) & (e9.shift(1) <= e20.shift(1))
    out["ema_cross_down"] = (e9 < e20) & (e9.shift(1) >= e20.shift(1))

    db = np.zeros(n, dtype=bool)
    dt_ = np.zeros(n, dtype=bool)
    lows, highs = _swing(df, "low", False), _swing(df, "high", True)
    cl = c.to_numpy(dtype=float)
    for a, b in zip(lows, lows[1:]):
        if b - a >= 4 and abs(l.iloc[a] - l.iloc[b]) <= 0.003 * l.iloc[a]:
            neck = float(h.iloc[a:b + 1].max())
            for i in range(b + 2, min(n, b + 12)):                    # break must come within an hour of the second bottom
                if cl[i] > neck:
                    db[i] = True
                    break
    for a, b in zip(highs, highs[1:]):
        if b - a >= 4 and abs(h.iloc[a] - h.iloc[b]) <= 0.003 * h.iloc[a]:
            neck = float(l.iloc[a:b + 1].min())
            for i in range(b + 2, min(n, b + 12)):
                if cl[i] < neck:
                    dt_[i] = True
                    break
    out["double_bottom"] = pd.Series(db, index=df.index)
    out["double_top"] = pd.Series(dt_, index=df.index)

    bf = np.zeros(n, dtype=bool)
    bearf = np.zeros(n, dtype=bool)
    for i in range(7, n):
        for pause in range(3, 7):                                      # 3-6 quiet bars after a 3-bar pole
            j = i - pause - 1                                          # last bar of the pole
            if j < 3:
                continue
            base = cl[j - 3]
            if base <= 0:
                continue
            pole = cl[j] / base - 1
            seg_h, seg_l = float(h.iloc[j + 1:i].max()), float(l.iloc[j + 1:i].min())
            if pole >= 0.006 and seg_h <= float(h.iloc[j]) * 1.001 and seg_l >= base + 0.5 * (cl[j] - base) and cl[i] > seg_h:
                bf[i] = True
                break
            if pole <= -0.006 and seg_l >= float(l.iloc[j]) * 0.999 and seg_h <= base + 0.5 * (cl[j] - base) and cl[i] < seg_l:
                bearf[i] = True
                break
    out["bull_flag"] = pd.Series(bf, index=df.index)
    out["bear_flag"] = pd.Series(bearf, index=df.index)
    return {k: v.fillna(False).astype(bool) for k, v in out.items()}
