"""Step 4 of the Upstox-budget plan: refresh a stock's candles only once per 5-minute slot instead of every minute (INTRADAY_CANDLE_REFRESH).

The scanner re-fetches the 5-minute candles of its 30 shortlisted stocks every cycle (about 30 of its ~39 calls a minute). Its analysis only treats a candle as completed 4m30s after the candle
opened (_analyse_candidate), so for four cycles out of five the list of completed candles does not change. This module is the SHADOW half of the plan: nothing about the live fetch changes.

    OFF      (default) nothing happens
    SHADOW   decisions still use the fresh candles every cycle. In addition, for each shortlisted stock the candles seen at the FIRST cycle of the current 5-minute slot are kept; at the other cycles of
             that slot the same stock is analysed again from those held candles (no API call) and compared with the real, fresh analysis. That is exactly what ENFORCE would have decided. One log line a
             cycle (CANDLE_REFRESH_CHECK) and one CSV row per difference (data/candle_refresh_shadow/<date>.csv).
    ENFORCE  not built yet: it is only written after SHADOW has shown the decisions agree. Treated as OFF.

SAFEGUARD (what ENFORCE would do for stocks that matter): held candles are never used to decide an entry. A stock is "near entry" when its analysis is actionable or its stage is an entry-ready or
pullback stage (near_entry). (1) HOT: a stock that was near entry on the previous cycle is fetched fresh every cycle, as today. (2) VERIFY: if the held candles make a stock look near entry, a fresh fetch is
made first and the fresh analysis decides. Everything else (quiet stocks) reuses the held candles. The cost of the safeguard is counted in the shadow (fetches if enforced = slot + hot + verify), and the one
remaining risk, a quiet stock that has just turned near-entry being seen up to a slot late, is counted as LATE.

A "decision" is stage, shortlist and actionable. Score differences are counted separately so a tiny drift is visible without being called a different decision.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

SCORE_TOLERANCE = 0.05
DECISION_FIELDS = ("stage", "shortlist", "actionable")
SCORE_FIELDS = ("score", "trade_quality_score", "movement_capture_score")
_TALLY = ("fetches_now", "fetches_if_enforced", "checks", "same_decision", "same_scores", "slot", "hot", "verify", "late")


def near_entry(candidate: Any) -> bool:
    """True when a stock is actionable or in an entry-ready / pullback stage: the stocks whose decision must always rest on fresh candles."""
    stage = str(getattr(candidate, "stage", "") or "")
    return bool(getattr(candidate, "actionable", False)) or "ENTRY_READY" in stage or "PULLBACK" in stage


def mode() -> str:
    m = os.getenv("INTRADAY_CANDLE_REFRESH", "OFF").strip().upper()
    return "SHADOW" if m == "SHADOW" else "OFF"        # ENFORCE is deliberately not available yet


def slot_of(now: datetime) -> int:
    """Index of the refresh slot the time falls in. The scanner counts a 5-minute candle as completed 4m30s after it opened, so the list of completed candles changes at hh:04:30, hh:09:30, ...
    and a slot therefore starts then, not at hh:05 (23 Nov: with slots starting at hh:05, 82 of the 86 decision differences came in the last minute of a slot, when the held list lacked the candle that had just completed)."""
    shifted = now + timedelta(seconds=30)
    return shifted.hour * 12 + shifted.minute // 5


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
        self.hot: set[str] = set()                       # near entry on the previous cycle
        self.next_hot: set[str] = set()                  # near entry on this cycle (becomes hot next cycle)
        self.day = ""
        self.total = {k: 0 for k in _TALLY}
        self.cycle = {k: 0 for k in _TALLY}

    def new_cycle(self, now: datetime) -> None:
        day = now.date().isoformat()
        if day != self.day:                              # a new session: nothing held, tallies restart
            self.day, self.held, self.hot, self.next_hot = day, {}, set(), set()
            self.total = {k: 0 for k in _TALLY}
        else:
            self.hot, self.next_hot = self.next_hot, set()
        self.cycle = {k: 0 for k in _TALLY}

    def due(self, symbol: str, now: datetime) -> bool:
        """True when ENFORCE would have to fetch this stock now (first time seen, or a new 5-minute slot)."""
        held = self.held.get(symbol)
        return held is None or held[0] != slot_of(now)

    def remember(self, symbol: str, now: datetime, candles: Any, why: str = "slot") -> None:
        """ENFORCE would fetch this stock now (new slot, hot, or verification): the fresh candles become the held ones for the slot."""
        self.held[symbol] = (slot_of(now), candles)
        self.cycle["fetches_if_enforced"] += 1
        self.cycle[why] += 1

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
