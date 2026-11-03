"""Corporate-event gate (SHADOW by default; ENFORCE on request; nothing here ever exits a trade).

Uses the event calendar (event_calendar.py). Buying an option into results means paying an inflated premium (implied volatility) for a binary, gap-prone outcome: a call can be right on direction and
still lose when the volatility collapses afterwards. The rule says "would block" when, at entry:

    results today, tomorrow or within APLUS_EVENT_PRE_DAYS (default 3, see event_calendar.NEAR_DAYS) trading days and NOT yet filed (ev_phase RESULTS_TODAY / RESULTS_TOMORROW / RESULTS_NEAR)
    a bonus or split ex-date today or tomorrow (the share price and the option series are being adjusted)

Not blocked, only tagged: results already filed since the last close (REPORTED: the premium is repriced), 1-3 trading days after results (POST), dividend ex-dates, buybacks and fund-raising meetings.

    evg_ok       0 when the rule would block, else 1.  Missing calendar data never blocks.
    evg_why      the reason in plain words
    APLUS_EVENT_GATE_MODE   OFF | SHADOW (default: tags only) | ENFORCE (a blocked candidate is not traded)

Evidence (16-23 Oct, 80 paper trades replayed through the calendar): the 16 trades that were taken with results today / tomorrow / within 3 trading days had an average entry IV of about 40 % against 31 %
for the rest, won 19 % against 25 %, and lost Rs 32k. Small sample from 6 sessions: stays in SHADOW until more sessions agree.
"""

from __future__ import annotations

import os
from typing import Any, Mapping


def mode() -> str:
    v = os.getenv("APLUS_EVENT_GATE_MODE", "SHADOW").strip().upper()
    return v if v in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def evaluate(rec: Mapping[str, Any]) -> dict[str, Any]:
    phase = str(rec.get("ev_phase") or "")
    why = []
    if phase in {"RESULTS_TODAY", "RESULTS_TOMORROW", "RESULTS_NEAR"}:
        days = rec.get("ev_results_days")
        when = "today" if phase == "RESULTS_TODAY" else "tomorrow" if phase == "RESULTS_TOMORROW" else f"in {days} trading days"
        why.append(f"results {when}: premium inflated")
    if str(rec.get("ev_ex_type") or "").upper() in {"BONUS", "SPLIT"}:
        why.append(f"{str(rec['ev_ex_type']).lower()} ex-date {'today' if rec.get('ev_ex_days') == 0 else 'tomorrow'}")
    return {"evg_ok": int(not why), "evg_why": "; ".join(why)}
