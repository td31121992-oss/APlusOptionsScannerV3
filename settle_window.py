"""Settle window: let the market settle before any trade fires (the scanner keeps scanning and collecting data the whole time).

    APLUS_SETTLE_MODE    OFF | SHADOW (default: records what it would have done, trades untouched) | ENFORCE (no new entry before APLUS_SETTLE_UNTIL)
    APLUS_SETTLE_UNTIL   HH:MM, default 10:00

    settle_until          the configured time
    settle_would_block    1 when the entry minute is before that time

Evidence (22 Sep - 21 Oct): real trades entered before 10:00 lost Rs 76k from 94 trades (45-56% hit the stop); entries 10:00-10:30 made +Rs 4k from 49 (59% reached +10%,
33% hit the stop). The same pattern shows in all signals measured minute by minute (stop-first 39% / 35% before 10:00 against 30% at 10:00-10:30).
"""

from __future__ import annotations

import os
from typing import Any


def mode() -> str:
    v = os.getenv("APLUS_SETTLE_MODE", "SHADOW").strip().upper()
    return v if v in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def until_minute() -> int:
    try:
        h, m = os.getenv("APLUS_SETTLE_UNTIL", "10:00").strip().split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return 10 * 60


def evaluate(minute: int) -> dict[str, Any]:
    u = until_minute()
    return {"settle_until": f"{u // 60:02d}:{u % 60:02d}", "settle_would_block": int(minute < u)}


def blocks(minute: int) -> bool:
    """True only in ENFORCE mode and before the settle time."""
    return mode() == "ENFORCE" and minute < until_minute()
