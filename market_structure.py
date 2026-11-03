"""Market-structure tags from today's completed 5-minute candles (SHADOW / RESEARCH - never blocks or changes a trade).

Swing points are 2-bar pivots (a bar whose high/low is beyond the two bars each side, so a swing is known 2 bars late - no look-ahead).

    ms_trend     UP (higher high + higher low) | DOWN (lower high + lower low) | RANGE   - from the last two swing highs and lows
    ms_bos       BULL | BEAR | ""   break of structure: a CLOSE beyond the last swing high (low) in the SAME direction as the trend
    ms_choch     BULL | BEAR | ""   change of character: a CLOSE beyond the last swing low (high) AGAINST the prior trend
    ms_mss       True when the CHOCH bar was an expansion candle (body >= 1.5x the average body) - a "market structure shift"
    ms_event_bars_ago   how many bars ago the BOS / CHOCH close happened (within the last 6 bars only)
    ms_fvg       BULL | BEAR | ""   the nearest still-unfilled fair-value gap inside the last 12 bars (3-candle gap)
    ms_fvg_dist_pct   price vs the near edge of that gap, in OUR direction (+ = price has already moved beyond/away in our favour)
    ms_aligned   True when the structure agrees with the trade (bull trade: trend UP or BOS/CHOCH BULL; bear: the mirror)
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

EVENT_WINDOW = 6
FVG_WINDOW = 12
MSS_BODY_X = 1.5


def _g(c: Any, name: str) -> float:
    try:
        v = c[name] if isinstance(c, Mapping) else getattr(c, name)
        return float(v)
    except (KeyError, AttributeError, TypeError, ValueError):
        return 0.0


def swings(highs: Sequence[float], lows: Sequence[float], k: int = 2) -> tuple[list[int], list[int]]:
    sh, sl = [], []
    for i in range(k, len(highs) - k):
        if highs[i] > max(highs[i - k:i]) and highs[i] > max(highs[i + 1:i + k + 1]):
            sh.append(i)
        if lows[i] < min(lows[i - k:i]) and lows[i] < min(lows[i + 1:i + k + 1]):
            sl.append(i)
    return sh, sl


def structure_tags(candles: Sequence[Any], direction: str, ltp: float | None = None) -> dict[str, Any]:
    try:
        cs = [c for c in candles if _g(c, "close") > 0]
        if len(cs) < 8:
            return {}
        o = [_g(c, "open") for c in cs]
        h = [_g(c, "high") for c in cs]
        l = [_g(c, "low") for c in cs]
        c_ = [_g(c, "close") for c in cs]
        n = len(cs)
        sh, sl = swings(h, l)
        trend = "RANGE"
        if len(sh) >= 2 and len(sl) >= 2:
            if h[sh[-1]] > h[sh[-2]] and l[sl[-1]] > l[sl[-2]]:
                trend = "UP"
            elif h[sh[-1]] < h[sh[-2]] and l[sl[-1]] < l[sl[-2]]:
                trend = "DOWN"
        bos = choch = ""
        ago = None
        mss = False
        bodies = [abs(c_[i] - o[i]) for i in range(n)]
        avg_body = sum(bodies) / n if n else 0.0
        # replay the recent bars: a swing counts only once it is confirmed (2 bars after it formed)
        for i in range(max(2, n - EVENT_WINDOW), n):
            hs = [j for j in sh if j + 2 <= i - 0 and j < i]
            ls = [j for j in sl if j + 2 <= i and j < i]
            if not hs or not ls:
                continue
            last_h, last_l = h[hs[-1]], l[ls[-1]]
            prior_up = len(hs) >= 2 and len(ls) >= 2 and h[hs[-1]] > h[hs[-2]] and l[ls[-1]] > l[ls[-2]]
            prior_dn = len(hs) >= 2 and len(ls) >= 2 and h[hs[-1]] < h[hs[-2]] and l[ls[-1]] < l[ls[-2]]
            if c_[i] > last_h:
                kind = "BOS" if prior_up else "CHOCH" if prior_dn else ""
                side = "BULL"
            elif c_[i] < last_l:
                kind = "BOS" if prior_dn else "CHOCH" if prior_up else ""
                side = "BEAR"
            else:
                continue
            if not kind:
                continue
            if kind == "BOS":
                bos, choch, ago, mss = side, "", n - 1 - i, False
            else:
                choch, bos, ago = side, "", n - 1 - i
                mss = avg_body > 0 and bodies[i] >= MSS_BODY_X * avg_body
        bull = str(direction).upper() == "BULLISH"
        px = float(ltp) if ltp and float(ltp) > 0 else c_[-1]
        fvg, fvg_dist = "", None
        for i in range(n - 1, max(1, n - FVG_WINDOW) - 1, -1):
            if i < 2:
                break
            if l[i] > h[i - 2]:                                   # bullish gap: low of bar i above high of bar i-2
                lo_edge, hi_edge, side = h[i - 2], l[i], "BULL"
            elif h[i] < l[i - 2]:                                 # bearish gap
                lo_edge, hi_edge, side = h[i], l[i - 2], "BEAR"
            else:
                continue
            later = range(i + 1, n)
            filled = any((l[j] <= lo_edge) if side == "BULL" else (h[j] >= hi_edge) for j in later)
            if filled:
                continue
            fvg = side
            near = hi_edge if side == "BULL" else lo_edge
            fvg_dist = round((1 if bull else -1) * (px / near - 1.0) * 100.0, 3) if near > 0 else None
            break
        want = "BULL" if bull else "BEAR"
        aligned = (trend == ("UP" if bull else "DOWN")) or bos == want or choch == want
        return {"ms_trend": trend, "ms_bos": bos, "ms_choch": choch, "ms_mss": bool(mss and choch),
                "ms_event_bars_ago": ago if ago is not None else "", "ms_fvg": fvg,
                "ms_fvg_dist_pct": fvg_dist if fvg_dist is not None else "", "ms_aligned": bool(aligned)}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
