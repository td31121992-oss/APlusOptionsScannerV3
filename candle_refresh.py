"""Step 4 of the Upstox-budget plan: refresh a stock's candles only once per 5-minute slot instead of every minute (INTRADAY_CANDLE_REFRESH).

The scanner re-fetches the 5-minute candles of its 30 shortlisted stocks every cycle (about 30 of its ~39 calls a minute). Its analysis only treats a candle as completed 4m30s after the candle
opened (_analyse_candidate), so for four cycles out of five the list of completed candles does not change. This module is the SHADOW half of the plan: nothing about the live fetch changes.

    OFF      (default) nothing happens
    SHADOW   decisions still use the fresh candles every cycle. In addition, for each shortlisted stock the candles seen at the FIRST cycle of the current 5-minute slot are kept; at the other cycles of
             that slot the same stock is analysed again from those held candles (no API call) and compared with the real, fresh analysis. That is exactly what ENFORCE would have decided. One log line a
             cycle (CANDLE_REFRESH_CHECK) and one CSV row per difference (data/candle_refresh_shadow/<date>.csv).
    ENFORCE  not built yet: it is only written after SHADOW has shown the decisions agree. Treated as OFF.

A "decision" is stage, shortlist and actionable. Score differences are counted separately so a tiny drift is visible without being called a different decision.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

SCORE_TOLERANCE = 0.05
DECISION_FIELDS = ("stage", "shortlist", "actionable")
SCORE_FIELDS = ("score", "trade_quality_score", "movement_capture_score")
_TALLY = ("fetches_now", "fetches_if_enforced", "checks", "same_decision", "same_scores")


def mode() -> str:
    m = os.getenv("INTRADAY_CANDLE_REFRESH", "OFF").strip().upper()
    return "SHADOW" if m == "SHADOW" else "OFF"        # ENFORCE is deliberately not available yet


def slot_of(now: datetime) -> int:
    """Index of the 5-minute slot the time falls in (a new slot starts at hh:00, hh:05, ...)."""
    return now.hour * 12 + now.minute // 5


def compare(stale: Any, fresh: Any) -> dict[str, Any]:
    """Compare two analysed candidates. same_decision: stage, shortlist and actionable equal. same_scores: every score within tolerance."""
    decision = [f for f in DECISION_FIELDS if getattr(stale, f, None) != getattr(fresh, f, None)]
    scores = []
    for f in SCORE_FIELDS:
        a, b = getattr(stale, f, None), getattr(fresh, f, None)
        try:
            if abs(float(a) - float(b)) > SCORE_TOLERANCE:
                scores.append(f)
        except (TypeError, ValueError):
            if a != b:
                scores.append(f)
    return {"same_decision": not decision, "same_scores": not scores, "decision_fields": decision, "score_fields": scores}


class Tracker:
    """Holds each stock's candles from the first cycle of the current slot, and the cycle / day tallies. One instance per scanner."""

    def __init__(self) -> None:
        self.held: dict[str, tuple[int, Any]] = {}
        self.day = ""
        self.total = {k: 0 for k in _TALLY}
        self.cycle = {k: 0 for k in _TALLY}

    def new_cycle(self, now: datetime) -> None:
        day = now.date().isoformat()
        if day != self.day:                              # a new session: nothing held, tallies restart
            self.day, self.held = day, {}
            self.total = {k: 0 for k in _TALLY}
        self.cycle = {k: 0 for k in _TALLY}

    def due(self, symbol: str, now: datetime) -> bool:
        """True when ENFORCE would have to fetch this stock now (first time seen, or a new 5-minute slot)."""
        held = self.held.get(symbol)
        return held is None or held[0] != slot_of(now)

    def remember(self, symbol: str, now: datetime, candles: Any) -> None:
        self.held[symbol] = (slot_of(now), candles)
        self.cycle["fetches_if_enforced"] += 1

    def held_candles(self, symbol: str) -> Any:
        return self.held[symbol][1]

    def record(self, result: dict[str, Any]) -> None:
        self.cycle["checks"] += 1
        self.cycle["same_decision"] += int(result["same_decision"])
        self.cycle["same_scores"] += int(result["same_scores"])

    def close_cycle(self, fetched_now: int) -> dict[str, int]:
        self.cycle["fetches_now"] = fetched_now
        for k, v in self.cycle.items():
            self.total[k] += v
        return dict(self.cycle)
