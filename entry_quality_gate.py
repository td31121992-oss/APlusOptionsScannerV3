"""Experimental, non-enforcing entry-quality gate.

This module only adds shadow diagnostics to candidate records. It must not
change candidate selection, paper-trade creation, or any execution mode.
Thresholds are initial hypotheses and must be validated by historical replay.
"""
from __future__ import annotations

import os
from typing import Any, Mapping


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result else default
    except (TypeError, ValueError, OverflowError):
        return default


def _threshold(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError, OverflowError):
        return default


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def evaluate(candidate: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    """Return shadow-only quality verdict and explainable reasons.

    Index disagreement and early clock time are deliberately not hard blockers:
    strong stock-specific momentum (e.g. TCS on 2026-10-16) must be evaluated
    separately from broad-index direction. This function never enforces a block.
    """
    ctx = context if isinstance(context, Mapping) else {}
    direction = str(candidate.get("direction") or "").strip().upper()
    sign = -1.0 if direction == "BEARISH" else 1.0

    selection = _num(candidate.get("selection_score"))
    movement = _num(candidate.get("movement_capture_score"))
    alignment = _num(candidate.get("trend_alignment_score"))
    clean = _num(candidate.get("clean_trend_score"))
    chase = _num(candidate.get("chase_risk_score"))
    recent15 = sign * _num(candidate.get("recent_move_15m_percent"))

    min_selection = _threshold("APLUS_QUALITY_MIN_SELECTION_SCORE", 80.0)
    min_movement = _threshold("APLUS_QUALITY_MIN_MOVEMENT_CAPTURE", 60.0)
    min_alignment = _threshold("APLUS_QUALITY_MIN_TREND_ALIGNMENT", 80.0)
    min_clean = _threshold("APLUS_QUALITY_MIN_CLEAN_TREND", 90.0)
    min_recent15 = _threshold("APLUS_QUALITY_MIN_DIRECTIONAL_15M_PCT", 0.50)
    max_chase = _threshold("APLUS_QUALITY_MAX_CHASE_RISK", 10.0)

    reasons: list[str] = []
    if selection < min_selection:
        reasons.append("SELECTION_SCORE_BELOW_MIN")
    if movement < min_movement:
        reasons.append("MOVEMENT_CAPTURE_BELOW_MIN")
    if alignment < min_alignment:
        reasons.append("TREND_ALIGNMENT_BELOW_MIN")
    if clean < min_clean:
        reasons.append("CLEAN_TREND_BELOW_MIN")
    if recent15 < min_recent15:
        reasons.append("DIRECTIONAL_15M_MOMENTUM_WEAK")
    if chase > max_chase:
        reasons.append("CHASE_RISK_HIGH")
    if str(candidate.get("selection_tier") or "").upper() == "WAIT_FOR_RETEST":
        reasons.append("WAIT_FOR_RETEST_NOT_CONFIRMED")
    if _truth(candidate.get("opt_late_guard20")) or _truth(candidate.get("opt_late_guard30")):
        reasons.append("OPTION_LATE_ENTRY_GUARD")

    # Index conflict is recorded as context only, never used alone to reject.
    rule_reasons = str(candidate.get("rule_reasons") or "")
    index_conflict = "AGAINST_INDEX" in rule_reasons.split("|")
    regime = str(candidate.get("day_regime") or ctx.get("regime") or "")

    return {
        "quality_gate_mode": "SHADOW_ONLY",
        "quality_gate_verdict": "PASS" if not reasons else "WOULD_BLOCK",
        "quality_gate_reasons": "|".join(dict.fromkeys(reasons)),
        "quality_gate_selection_score": round(selection, 2),
        "quality_gate_movement_capture": round(movement, 2),
        "quality_gate_trend_alignment": round(alignment, 2),
        "quality_gate_clean_trend": round(clean, 2),
        "quality_gate_directional_15m_pct": round(recent15, 3),
        "quality_gate_chase_risk": round(chase, 2),
        "quality_gate_index_conflict_context": index_conflict,
        "quality_gate_regime_context": regime,
    }
