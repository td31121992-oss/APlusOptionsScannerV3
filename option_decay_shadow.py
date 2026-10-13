"""Shadow-only option premium decay/stalling evaluator for paper trades."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Mapping

DEFAULT_CONFIG = {
    "stall_minutes": 60.0,
    "strong_stall_minutes": 90.0,
    "min_favorable_underlying_move_pct": 2.0,
    "max_retrace_from_peak_pct_points": 0.75,
    "min_option_drawdown_pct": 5.0,
    "strong_option_drawdown_pct": 8.0,
}

def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (TypeError, ValueError):
        return default

def _dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except (TypeError, ValueError):
        return None

def evaluate_decay_shadow(trade: Mapping[str, Any], *, underlying_price: Any,
                           option_price: Any, when: datetime,
                           config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Calculate shadow metrics only; never mutates or closes the supplied trade."""
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(config, Mapping):
        cfg.update(config)
    u0, o0 = _num(trade.get("underlying_entry")), _num(trade.get("entry_price"))
    u, o = _num(underlying_price), _num(option_price)
    if min(u0, o0, u, o) <= 0:
        return {"shadow_exit_planner_mode": "SHADOW_ONLY",
                "shadow_exit_planner_verdict": "INSUFFICIENT_DATA_SHADOW",
                "shadow_exit_planner_updated_at": when.isoformat()}

    entry_time = _dt(trade.get("entry_time")) or when
    if entry_time.tzinfo and when.tzinfo is None:
        when = when.replace(tzinfo=entry_time.tzinfo)
    elif when.tzinfo and entry_time.tzinfo is None:
        entry_time = entry_time.replace(tzinfo=when.tzinfo)
    old_up = max(u0, _num(trade.get("shadow_underlying_peak"), u0))
    old_op = max(o0, _num(trade.get("shadow_option_peak"), o0))
    old_up_at = _dt(trade.get("shadow_underlying_peak_at")) or entry_time
    old_op_at = _dt(trade.get("shadow_option_peak_at")) or entry_time
    up, up_at = (u, when) if u >= old_up else (old_up, old_up_at)
    op, op_at = (o, when) if o >= old_op else (old_op, old_op_at)

    holding = max(0.0, (when-entry_time).total_seconds()/60.0)
    stalled = max(0.0, (when-up_at).total_seconds()/60.0)
    move = (u/u0-1)*100
    peak_move = (up/u0-1)*100
    retrace = peak_move-move
    option_change = (o/o0-1)*100
    option_dd = max(0.0, (op-o)/op*100) if op else 0.0
    qualified = peak_move >= _num(cfg.get("min_favorable_underlying_move_pct"), 2.0)
    retrace_ok = retrace <= _num(cfg.get("max_retrace_from_peak_pct_points"), 0.75)
    stalled_ok = stalled >= _num(cfg.get("stall_minutes"), 60.0) and retrace_ok
    strong_stalled = stalled >= _num(cfg.get("strong_stall_minutes"), 90.0) and retrace_ok
    if qualified and strong_stalled and option_dd >= _num(cfg.get("strong_option_drawdown_pct"), 8.0):
        verdict = "EXIT_CANDIDATE_SHADOW"
    elif qualified and stalled_ok and option_dd >= _num(cfg.get("min_option_drawdown_pct"), 5.0):
        verdict = "DECAY_RISK_SHADOW"
    else:
        verdict = "NO_DECAY_EXIT_SIGNAL_SHADOW"
    return {
        "shadow_exit_planner_mode": "SHADOW_ONLY",
        "shadow_exit_planner_verdict": verdict,
        "shadow_exit_planner_updated_at": when.isoformat(),
        "shadow_exit_planner_holding_minutes": round(holding, 2),
        "shadow_exit_planner_minutes_since_underlying_peak": round(stalled, 2),
        "shadow_exit_planner_underlying_move_pct": round(move, 4),
        "shadow_exit_planner_underlying_peak_move_pct": round(peak_move, 4),
        "shadow_exit_planner_retrace_from_peak_pct_points": round(retrace, 4),
        "shadow_exit_planner_option_change_pct": round(option_change, 4),
        "shadow_exit_planner_option_drawdown_pct": round(option_dd, 4),
        "shadow_underlying_peak": round(up, 4),
        "shadow_underlying_peak_at": up_at.isoformat(),
        "shadow_option_peak": round(op, 4),
        "shadow_option_peak_at": op_at.isoformat(),
        "shadow_exit_planner_qualified_move": bool(qualified),
        "shadow_exit_planner_underlying_stalled": bool(stalled_ok),
        "shadow_exit_planner_note": "Research only; not proof of theta decay. IV, spread, strike, expiry and quote quality can affect premium.",
    }
