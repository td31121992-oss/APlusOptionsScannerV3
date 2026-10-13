"""Entry rules built from the Oct 2026 study (index-agreement + same-side cap).

APLUS_ENTRY_RULES_MODE:
  OFF      - nothing recorded, nothing blocked
  SHADOW   - (default) every paper trade is tagged with what the rules WOULD have done; nothing is blocked
  ENFORCE  - candidates that fail are not entered (status ENTRY_RULE_BLOCKED)

Rules (all must pass):
  1. time   : no new entry before APLUS_ENTRY_RULES_START (default 10:00)
  2. index  : the trade direction must agree with NIFTY's move since today's open (calls need NIFTY up, puts need NIFTY down).
              If the index move is unknown the rule passes, so a data glitch never stops trading.
  3. cap    : at most APLUS_ENTRY_RULES_MAX_PER_SIDE (default 3) open positions in the same direction, since same-side trades are
              one correlated bet, not independent ones.
"""

from __future__ import annotations

import os
from typing import Any


def mode() -> str:
    value = os.getenv("APLUS_ENTRY_RULES_MODE", "SHADOW").strip().upper()
    return value if value in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def _start_minute() -> int:
    try:
        h, m = os.getenv("APLUS_ENTRY_RULES_START", "10:00").strip().split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return 10 * 60


def _max_per_side() -> int:
    try:
        return max(1, int(os.getenv("APLUS_ENTRY_RULES_MAX_PER_SIDE", "3")))
    except ValueError:
        return 3


def evaluate(direction: str, minute: int, nifty_pct_open: Any, open_same_side: int) -> dict[str, Any]:
    reasons = []
    if minute < _start_minute():
        reasons.append("TOO_EARLY")
    try:
        move = float(nifty_pct_open)
        known = move == move
    except (TypeError, ValueError):
        move, known = 0.0, False
    if known:
        bull = str(direction).upper() == "BULLISH"
        if (bull and move <= 0) or (not bull and move >= 0):
            reasons.append("AGAINST_INDEX")
    if open_same_side >= _max_per_side():
        reasons.append("SIDE_CAP")
    return {"rule_verdict": "PASS" if not reasons else "WOULD_BLOCK", "rule_reasons": "|".join(reasons),
            "rule_nifty_pct_open": round(move, 3) if known else "", "rule_open_same_side": int(open_same_side)}
