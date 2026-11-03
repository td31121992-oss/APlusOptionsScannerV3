"""Market brake as a SHADOW tag (recorded on the candidate / trade, never blocks anything).

History (22 Sep - 21 Oct, 175 trades with Nifty data): when Nifty had moved >= 0.3% against the trade's direction between the open and the entry, 17 trades lost
Rs 19.9k (18% won); when it was with us by more than 0.3%, 71 trades made +Rs 2.6k. When Nifty had fallen against us over the last 15 minutes, 17 trades lost Rs 20.8k.

    mb_nifty_open_dir    Nifty % move from the open to now, in OUR direction (positive = the market is with us)
    mb_nifty_15_dir      change of that move over the last ~15 minutes, in our direction (percentage points; blank until we have a reading 12+ minutes old)
    mb_would_block       1 when the open move is <= -OPEN_AGAINST_PCT or the 15-minute change is <= -TREND_AGAINST_PCT, else 0
    mb_reason            OPEN_AGAINST / TREND_AGAINST / both joined with |

The thresholds are env-tunable (APLUS_MB_OPEN_AGAINST_PCT 0.3, APLUS_MB_TREND_AGAINST_PCT 0.1). Only records; the review compares would-block trades with what they did.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Any

_hist: deque = deque(maxlen=400)           # (epoch seconds, nifty % from open)
MIN_AGE, MAX_AGE = 12 * 60, 25 * 60


def _thr(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def brake_tags(direction: str, nifty_pct_open: Any, now: float | None = None) -> dict[str, Any]:
    try:
        move = float(nifty_pct_open)
        if move != move:
            return {}
        now = time.time() if now is None else now
        sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
        old = [h for h in _hist if MIN_AGE <= now - h[0] <= MAX_AGE]
        out: dict[str, Any] = {"mb_nifty_open_dir": round(sign * move, 3)}
        trend = None
        if old:
            trend = sign * (move - old[-1][1])
            out["mb_nifty_15_dir"] = round(trend, 3)
        if not _hist or now - _hist[-1][0] >= 30:
            _hist.append((now, move))
        reasons = []
        if sign * move <= -_thr("APLUS_MB_OPEN_AGAINST_PCT", 0.3):
            reasons.append("OPEN_AGAINST")
        if trend is not None and trend <= -_thr("APLUS_MB_TREND_AGAINST_PCT", 0.1):
            reasons.append("TREND_AGAINST")
        out["mb_would_block"] = int(bool(reasons))
        out["mb_reason"] = "|".join(reasons)
        return out
    except (TypeError, ValueError):
        return {}
