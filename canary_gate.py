"""'Canary' entry gate: do not pile more trades onto a side that is not working yet (SHADOW by default; ENFORCE on request; nothing here ever exits a trade).

Many losing trades come in clusters: several trades in the same direction within minutes of each other are really ONE bet on the market, and when it is wrong they all stop out
together (22 Oct: five puts opened 10:05-10:19, all stopped, -Rs 27k).  The rule: a new trade in a direction is allowed when

    * no trade in that direction was opened in the last WINDOW_MIN minutes (the first one is the canary), or
    * at least one of those earlier same-direction trades is already MIN_AGE_MIN minutes old and has shown a gain of MIN_GAIN_PCT or more.

    APLUS_CANARY_MODE        OFF | SHADOW (default: tags only) | ENFORCE (a candidate that fails is not traded)
    APLUS_CANARY_WINDOW_MIN  30      APLUS_CANARY_MIN_AGE_MIN  5      APLUS_CANARY_MIN_GAIN_PCT  5

    cn_ok            1 when the candidate may be taken, 0 when the rule would block it
    cn_reason        FIRST_OF_WINDOW / CANARY_OK / NO_CANARY_PROFIT
    cn_recent        same-direction trades opened in the window
    cn_best_gain_pct the best gain any of them has shown so far

Replay on 119 closed trades, 12-22 Oct: kept 41 (5.1 a day) at -Rs 34k against -Rs 130k for all of them; blocked 78 (-Rs 95k) including 15 winners (+Rs 69k). It improved 5 of the 8 days.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterable, Mapping


def mode() -> str:
    v = os.getenv("APLUS_CANARY_MODE", "SHADOW").strip().upper()
    return v if v in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _when(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def evaluate(trades: Iterable[Mapping[str, Any]], direction: str, now: datetime) -> dict[str, Any]:
    window, min_age, min_gain = _num("APLUS_CANARY_WINDOW_MIN", 30), _num("APLUS_CANARY_MIN_AGE_MIN", 5), _num("APLUS_CANARY_MIN_GAIN_PCT", 5)
    recent = []
    for t in trades:
        if str(t.get("direction") or "").upper() != str(direction).upper():
            continue
        et = _when(t.get("entry_time"))
        if et is None or (et.tzinfo is None) != (now.tzinfo is None):
            continue
        age = (now - et).total_seconds() / 60.0
        if 0 <= age <= window:
            entry = _f(t.get("entry_price"))
            gain = (_f(t.get("highest_option_price")) / entry - 1.0) * 100.0 if entry > 0 else 0.0
            recent.append((age, gain))
    if not recent:
        return {"cn_ok": 1, "cn_reason": "FIRST_OF_WINDOW", "cn_recent": 0, "cn_best_gain_pct": ""}
    best = max(g for _, g in recent)
    ok = any(age >= min_age and gain >= min_gain for age, gain in recent)
    return {"cn_ok": int(ok), "cn_reason": "CANARY_OK" if ok else "NO_CANARY_PROFIT", "cn_recent": len(recent), "cn_best_gain_pct": round(best, 1)}
