"""Candle-history cache for the scanner (Option A of the fast-scan plan). Behaviour is chosen by the environment variable INTRADAY_HISTORY_CACHE:

    OFF       (default) the scanner fetches the full 8-day history of every shortlisted stock every cycle, exactly as before
    SHADOW    decisions still use that full fetch; in addition the cached path is run for a few stocks each cycle and compared with it (one log line per cycle: HISTORY_CACHE_CHECK)
    ENFORCE   the scanner uses the cached path; every 10th cycle it also fetches two stocks the old way and compares (HISTORY_CACHE_SPOTCHECK), dropping that stock's cache on a difference

Why: the Upstox client answers one history request with TWO REST calls - one for the completed sessions (8 days, which never change during the day) and one for today. Measured on 28 Oct 2026,
history was 13.4 of the 21.7 seconds of an average cycle. The completed sessions are fetched once per stock per day and kept; each cycle then asks only for today's candles (the request is made
with a start date of today, so the client makes just the one call). The merged list is the same list the old single request returned.

Pure helpers live here so they can be tested without a scanner.
"""

from __future__ import annotations

import os
from datetime import datetime, time as clock_time, timedelta, tzinfo
from typing import Any, Sequence

MODES = ("OFF", "SHADOW", "ENFORCE")
SHADOW_SAMPLE = 5
SPOTCHECK_EVERY = 10          # ENFORCE: every 10th cycle ...
SPOTCHECK_SAMPLE = 2          # ... the full history of the first two stocks is fetched the old way and compared with the cached result


def mode() -> str:
    m = os.getenv("INTRADAY_HISTORY_CACHE", "OFF").strip().upper()
    return m if m in MODES else "OFF"


def windows(now: datetime, calendar_days: int, session_start: clock_time, tz: tzinfo) -> tuple[datetime, datetime, datetime, datetime]:
    """(past_from, past_to, today_from, today_to): the past request ends at the end of yesterday, so it never reaches into today."""
    today_start = datetime.combine(now.date(), session_start, tzinfo=tz)
    past_from = datetime.combine(now.date() - timedelta(days=calendar_days), session_start, tzinfo=tz)
    past_to = datetime.combine(now.date() - timedelta(days=1), clock_time(23, 59), tzinfo=tz)       # the end of yesterday: a request ending today would also return (and freeze) today's candles
    return past_from, past_to, today_start, now + timedelta(minutes=1)


def merge(past: Sequence[Any], today: Sequence[Any]) -> list[Any]:
    """Past sessions plus today's candles, one per timestamp (today's wins), oldest first."""
    by_ts = {c.timestamp: c for c in past}
    by_ts.update({c.timestamp: c for c in today})
    return [by_ts[k] for k in sorted(by_ts)]


def compare(full: Sequence[Any], cached: Sequence[Any]) -> dict[str, Any]:
    """Compare two candle lists on the candles that were COMPLETE when the first (full) fetch was made: everything older than its newest candle. The cached fetch is taken a little later, so it may
    hold newer candles (or a newer version of the forming one); those are ignored, never reported as a difference."""
    full = list(full)
    if not full:
        return {"identical": not list(cached), "different": 0, "missing": len(list(cached)), "compared": 0}
    cutoff = full[-1].timestamp
    a = {c.timestamp: c for c in full if c.timestamp < cutoff}
    b = {c.timestamp: c for c in cached if c.timestamp < cutoff}
    common = set(a) & set(b)
    diff = sorted(ts for ts in common if (a[ts].open, a[ts].high, a[ts].low, a[ts].close, a[ts].volume) != (b[ts].open, b[ts].high, b[ts].low, b[ts].close, b[ts].volume))
    missing = len(set(a) - set(b)) + len(set(b) - set(a))
    return {"identical": not diff and not missing, "different": len(diff), "missing": missing, "compared": len(common)}
