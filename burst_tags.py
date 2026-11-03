"""Volume-burst shadow tags at entry (SHADOW ONLY - recorded on the trade, never used to allow or block anything).

From today's completed 5-minute candles of the stock (oldest first), "usual pace" = the median bar volume so far today (the same measure the
Why-is-it-moving panel uses):

    bu_last_x         volume of the last completed bar / usual pace
    bu_max_x          the biggest bar so far / usual pace;  bu_max_ago = how many bars ago it was (0 = the last bar)
    bu_max_aligned    that biggest bar closed in OUR direction (up bar for calls, down bar for puts)
    bu_n3             number of bars at 3x the usual pace or more
A 10-day replay of 4x+ bursts in the first 30 minutes showed no standalone edge (up bursts +0.2%, down bursts bounced), so this only records
the ratio to see whether it adds anything next to the sector, leader and pivot tags.
"""

from __future__ import annotations

import statistics as st
from typing import Any, Sequence

import chop

MIN_BARS = 4


def burst_tags(candles: Sequence[Any], direction: str) -> dict[str, Any]:
    try:
        bars = chop._bars(candles)
        if len(bars) < MIN_BARS:
            return {}
        vols = [b[4] for b in bars]
        med = st.median(vols)
        if med <= 0:
            return {}
        i = max(range(len(vols)), key=lambda k: vols[k])
        bull = str(direction).upper() == "BULLISH"
        up_bar = bars[i][3] >= bars[i][0]
        return {"bu_last_x": round(vols[-1] / med, 1), "bu_max_x": round(vols[i] / med, 1), "bu_max_ago": len(vols) - 1 - i,
                "bu_max_aligned": bool(up_bar == bull), "bu_n3": int(sum(1 for v in vols if v >= 3 * med))}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
