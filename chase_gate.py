"""'Do not chase strength' check (SHADOW by default; ENFORCE on request; nothing here ever exits a trade).

Buying an option after the move has already happened is the most expensive habit in our own results. Two things mark a chase, both read from tags the scanner already puts on the candidate:

    fast run   the stock has already moved at least APLUS_CHASE_LAST15_PCT (default 0.30) percent OUR way in the last 15 minutes      (ctx_last15_pct, signed in our direction)
    extended   (calls only) more than APLUS_CHASE_BREADTH_PCT (default 60) percent of F&O stocks are already above their own VWAP     (bs_breadth_pct for a call)

    cg_fast15   the stock's 15-minute move in our direction, percent
    cg_fast     1 when the fast-run condition holds
    cg_extended 1 when the market-extended condition holds (calls only; absent for puts)
    cg_done_pct / cg_range_pos   the move already made today and the position in the day's range (tags only, never used)
    cg_why      which condition fired
    cg_ok       0 when the rule would block (either condition), else 1.  Missing data is never a chase.
    APLUS_CHASE_GATE_MODE   OFF | SHADOW (default: tags only) | ENFORCE (a chase candidate is not traded)

Evidence (15-23 Oct, 92 trades that carry the entry-context tags, 6 sessions): entries after a 15-minute run of 0.3 % or more our way won 6 % of the time and lost Rs 74k (31 trades; calls 18, puts 13);
the other 61 won 34 %. Calls entered with more than 60 % of stocks above VWAP won 14 % and lost Rs 47k (29 trades, 1-22 Oct). Small samples from a handful of sessions: this stays in SHADOW until more
sessions agree.
"""

from __future__ import annotations

import os
from typing import Any, Mapping


def mode() -> str:
    v = os.getenv("APLUS_CHASE_GATE_MODE", "SHADOW").strip().upper()
    return v if v in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def evaluate(rec: Mapping[str, Any], direction: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    why = []
    move15 = _f(rec.get("ctx_last15_pct"))
    if move15 is not None:
        out["cg_fast15"] = round(move15, 2)
        out["cg_fast"] = int(move15 >= _num("APLUS_CHASE_LAST15_PCT", 0.30))
        if out["cg_fast"]:
            why.append(f"stock +{move15:.2f}% in 15m")
    if str(direction).upper() == "BULLISH":
        breadth = _f(rec.get("bs_breadth_pct"))                      # a call: the share of stocks ABOVE their VWAP
        if breadth is not None:
            out["cg_extended"] = int(breadth > _num("APLUS_CHASE_BREADTH_PCT", 60.0))
            if out["cg_extended"]:
                why.append(f"market extended {breadth:.0f}%")
    for src, key in (("ctx_done_move_pct", "cg_done_pct"), ("ctx_range_pos", "cg_range_pos")):      # recorded only: in the data neither separated winners from losers, so they never decide
        v = _f(rec.get(src))
        if v is not None:
            out[key] = round(v, 2)
    out["cg_why"] = "|".join(why)
    out["cg_ok"] = int(not why)
    return out
