"""Choppiness measures: is this stock trending or just going sideways? (DISPLAY + SHADOW only - never blocks or changes a trade.)

Computed from today's completed 5-minute candles (oldest first):

    chop_vwap_x30     times price crossed VWAP in the last 6 bars (30 minutes)
    chop_vwap_x60     times price crossed VWAP in the last 12 bars (60 minutes)
    chop_ci14         Choppiness Index over 14 bars, 0-100:  100 * log10(sum of true ranges / (highest high - lowest low)) / log10(14)
                      high (above ~61.8) = sideways chop, low (below ~38.2) = a clean trend
    chop_er12         efficiency ratio over 12 bars, 0-1:  net move / sum of every bar-to-bar move. 1 = straight line, near 0 = going nowhere
    chop_state        TRENDING | MIXED | CHOPPY
        CHOPPY    when ci14 >= 61.8, or 3+ VWAP crosses in 60 minutes, or er12 < 0.20
        TRENDING  when ci14 <= 45 and er12 >= 0.40 and at most 1 VWAP cross in 60 minutes
        MIXED     otherwise
These are standard indicators with common thresholds, not tuned values: the nightly review shows whether they separate outcomes.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

CI_LEN = 14
ER_LEN = 12
MIN_BARS = 8                  # from about 09:50 on; before CI_LEN+1 bars exist the windows shrink to what is available (see chop_len)
CHOPPY_CI = 61.8
TREND_CI = 45.0


def _bars(candles: Sequence[Any]) -> list[tuple[float, float, float, float, float]]:
    out = []
    for c in candles or []:
        try:
            if isinstance(c, Mapping):
                o, h, l, cl = c.get("o", c.get("open")), c.get("h", c.get("high")), c.get("l", c.get("low")), c.get("c", c.get("close"))
                v = c.get("v", c.get("volume", 0))
            else:
                o, h, l, cl, v = c.open, c.high, c.low, c.close, getattr(c, "volume", 0)
            o, h, l, cl, v = float(o), float(h), float(l), float(cl), float(v or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if cl > 0:
            out.append((o, h, l, cl, v))
    return out


def measures(candles: Sequence[Any]) -> dict[str, Any]:
    bars = _bars(candles)
    n = len(bars)
    if n < MIN_BARS:
        return {}
    ci_len = min(CI_LEN, n - 1)
    er_len = min(ER_LEN, n - 1)
    try:
        cum_pv = cum_v = 0.0
        side: list[int] = []
        for o, h, l, c, v in bars:
            w = v if v > 0 else 1.0                              # a missing volume falls back to an equal weighting
            cum_pv += ((h + l + c) / 3.0) * w
            cum_v += w
            vw = cum_pv / cum_v
            side.append(1 if c >= vw else -1)

        def crosses(k: int) -> int:
            seg = side[-(k + 1):]
            return sum(1 for a, b in zip(seg, seg[1:]) if a != b)

        window = bars[-ci_len:]
        prev_close = bars[-ci_len - 1][3]
        tr_sum = 0.0
        pc = prev_close
        for o, h, l, c, v in window:
            tr_sum += max(h - l, abs(h - pc), abs(l - pc))
            pc = c
        rng = max(b[1] for b in window) - min(b[2] for b in window)
        ci = 100.0 * math.log10(tr_sum / rng) / math.log10(ci_len) if rng > 0 and tr_sum > 0 and ci_len > 1 else 100.0
        ci = max(0.0, min(100.0, ci))
        closes = [b[3] for b in bars[-(er_len + 1):]]
        path = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
        er = abs(closes[-1] - closes[0]) / path if path > 0 else 0.0
        x30, x60 = crosses(6), crosses(12)
        if ci >= CHOPPY_CI or x60 >= 3 or er < 0.20:
            state = "CHOPPY"
        elif ci <= TREND_CI and er >= 0.40 and x60 <= 1:
            state = "TRENDING"
        else:
            state = "MIXED"
        return {"chop_vwap_x30": x30, "chop_vwap_x60": x60, "chop_ci14": round(ci, 1), "chop_er12": round(er, 2), "chop_state": state, "chop_len": ci_len}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}


def badge_text(m: Mapping[str, Any]) -> str:
    if not m:
        return ""
    word = {"TRENDING": "Trending", "MIXED": "Mixed", "CHOPPY": "Choppy"}.get(str(m.get("chop_state")), "")
    return (f"{word}: {m.get('chop_vwap_x60', 0)} VWAP crosses in 60 min, choppiness index {m.get('chop_ci14', 0):.0f}, "
            f"efficiency {m.get('chop_er12', 0):.2f}")
