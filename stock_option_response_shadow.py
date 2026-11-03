"""
APlus stock-vs-option response tracker — SHADOW ONLY.

Pure calculations; does not place orders, close trades, or mutate trade state.
Call evaluate_response() on fresh underlying and option quotes for an open paper trade.
Persist returned snapshots separately if desired.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Mapping

EPS = 1e-12

def _num(value: Any):
    try:
        x = float(value)
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return x
    except (TypeError, ValueError):
        return None

def _dt(value: Any):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        s = str(value).strip().replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None

def _pct(now, start):
    if now is None or start is None or abs(start) < EPS:
        return None
    return (now / start - 1.0) * 100.0

def evaluate_response(trade: Mapping[str, Any],
                      underlying_price: Any,
                      option_price: Any,
                      quote_time: Any = None,
                      day_reference_price: Any = None,
                      config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """
    Expected trade fields:
      paper_trade_id, side ('CE'/'CALL' or 'PE'/'PUT'),
      underlying_entry_price, option_entry_price, entry_time,
      day_reference_price (optional; e.g. prior close).
    quote_time should be ISO-8601. If absent, current UTC time is used.
    day_reference_price may be passed explicitly or read from trade.
    """
    cfg = {
        "max_quote_age_seconds": 180,
        "milestones_pct": [0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 2.50, 3.00],
        "mode": "SHADOW_ONLY",
    }
    if config:
        cfg.update(dict(config))

    now = _dt(quote_time) or datetime.now(timezone.utc)
    under = _num(underlying_price)
    opt = _num(option_price)
    u_entry = _num(trade.get("underlying_entry_price", trade.get("underlying_entry")))
    o_entry = _num(trade.get("option_entry_price", trade.get("entry_price")))
    day_ref = _num(day_reference_price if day_reference_price is not None
                   else trade.get("day_reference_price", trade.get("underlying_day_reference")))
    entry_time = _dt(trade.get("entry_time"))

    out = {
        "shadow_mode": "SHADOW_ONLY",
        "shadow_feature": "stock_option_response",
        "paper_trade_id": trade.get("paper_trade_id", trade.get("trade_id")),
        "quote_time": now.isoformat(),
        "underlying_price": under,
        "option_price": opt,
        "underlying_entry_price": u_entry,
        "option_entry_price": o_entry,
        "day_reference_price": day_ref,
        "underlying_move_from_entry_pct": _pct(under, u_entry),
        "option_change_from_entry_pct": _pct(opt, o_entry),
        "option_change_from_entry_rupees": (opt - o_entry) if opt is not None and o_entry is not None else None,
        "stock_move_from_day_reference_at_entry_pct": _pct(u_entry, day_ref),
        "stock_move_from_day_reference_now_pct": _pct(under, day_ref),
        "stock_move_since_entry_percentage_points": None,
        "option_response_per_1pct_stock_move": None,
        "elapsed_minutes": None,
        "quote_age_seconds": 0,
        "verdict": "INSUFFICIENT_DATA_SHADOW",
        "note": "Missing or invalid entry/quote prices; no inference made.",
    }

    sm = out["underlying_move_from_entry_pct"]
    op = out["option_change_from_entry_pct"]
    if sm is not None and abs(sm) > EPS and op is not None:
        out["option_response_per_1pct_stock_move"] = op / sm
    if entry_time:
        out["elapsed_minutes"] = max(0.0, (now - entry_time).total_seconds() / 60.0)
    if under is not None and day_ref is not None and u_entry is not None:
        at_entry = _pct(u_entry, day_ref)
        now_day = _pct(under, day_ref)
        if at_entry is not None and now_day is not None:
            out["stock_move_since_entry_percentage_points"] = now_day - at_entry

    if under is None or opt is None or u_entry is None or o_entry is None or u_entry <= 0 or o_entry <= 0:
        return out

    side = str(trade.get("side", trade.get("option_type", ""))).upper()
    is_put = side in {"PE", "PUT", "P"}
    signed_stock_move = -sm if is_put else sm
    signed_option_change = op
    if signed_stock_move is None or signed_option_change is None:
        return out

    if signed_stock_move >= 0.25 and signed_option_change > 0:
        verdict = "FAVORABLE_MOVE_OPTION_RESPONDED_SHADOW"
        note = "Underlying moved in the favorable direction and option premium rose."
    elif signed_stock_move >= 0.25 and signed_option_change <= 0:
        verdict = "FAVORABLE_STOCK_WEAK_OPTION_RESPONSE_SHADOW"
        note = "Underlying moved favorably but option premium did not rise; inspect theta, IV, delta, spread and quote freshness."
    elif signed_stock_move <= -0.25 and signed_option_change < 0:
        verdict = "ADVERSE_MOVE_OPTION_LOSS_SHADOW"
        note = "Underlying moved against the position and option premium fell."
    elif signed_stock_move <= -0.25 and signed_option_change >= 0:
        verdict = "DIVERGENT_RESPONSE_SHADOW"
        note = "Underlying moved against the position but option premium did not fall; verify quotes and Greeks."
    else:
        verdict = "SMALL_MOVE_MONITOR_SHADOW"
        note = "Underlying move is small; continue measuring response and elapsed time."

    out["verdict"] = verdict
    out["note"] = note
    out["favorable_underlying_move_pct"] = signed_stock_move
    out["option_response_pct"] = signed_option_change
    out["milestones"] = []
    for milestone in cfg.get("milestones_pct", []):
        try:
            m = float(milestone)
        except (TypeError, ValueError):
            continue
        if signed_stock_move >= m:
            out["milestones"].append({
                "favorable_stock_move_pct": m,
                "observed_option_change_pct": signed_option_change,
                "observed_option_change_rupees": opt - o_entry,
                "quote_time": now.isoformat(),
                "elapsed_minutes": out["elapsed_minutes"],
            })
    return out
