"""Read-only view of a trade's stop-loss: where it started, where it is now, and why it moved (dashboard / journal only).

It reproduces, from the trade's saved fields, the same protective-stop logic the paper journal uses - it never changes a trade:

    start_sl   the stop set at entry (option_stop)
    cur_sl     the stop that would exit the trade now
    sl_label   why it is there:  Initial | Ladder +x% | T1 hit: at cost | T2 hit: +8% | Runner: 70% of peak | Profit lock | Manual
    sl_next    what moves it next (price and the new stop), or ""
"""

from __future__ import annotations

import os
from typing import Any, Mapping


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _ladder_lock_pct(entry: float, high: float) -> float | None:
    import paper_trade_journal as pj

    floor = pj.user_ladder_floor(entry, high)
    return round((floor / entry - 1.0) * 100.0, 1) if floor > 0 and entry > 0 else None


def stop_state(t: Mapping[str, Any], ladder_mode: str | None = None, profit_lock_mode: str | None = None) -> dict[str, Any]:
    entry, high = _f(t.get("entry_price")), _f(t.get("highest_option_price"))
    start = _f(t.get("option_stop"))
    if entry <= 0 or start <= 0:
        return {}
    ladder_mode = (ladder_mode or os.getenv("APLUS_EXIT_LADDER_MODE", "SHADOW")).strip().upper()
    lock_mode = (profit_lock_mode or os.getenv("APLUS_PROFIT_LOCK_MODE", "SHADOW")).strip().upper()
    cur, label, nxt = start, "Initial", ""
    if ladder_mode == "ENFORCE":
        import paper_trade_journal as pj

        floor = pj.user_ladder_floor(entry, high)
        if floor > cur:
            cur, label = floor, f"Ladder {_ladder_lock_pct(entry, high):+g}%"
        gain = (high / entry - 1.0) * 100.0 if high > 0 else 0.0
        steps = [(5.0, pj._first_lock_pct()), (10.0, 3.0), (20.0, 13.0), (30.0, 22.0)]
        nxt_gain = next((g for g, _ in steps if gain < g), None)
        if nxt_gain is None:
            nxt_gain = 30.0 + 5.0 * (int((gain - 30.0) // 5.0) + 1)
            lock = 22.0 + 2.0 * (int((nxt_gain - 30.0) // 5.0))
        else:
            lock = dict(steps)[nxt_gain]
        nxt = f"at {entry * (1 + nxt_gain / 100):.2f} (+{nxt_gain:g}%) stop moves to {entry * (1 + lock / 100):.2f}"
    else:
        t1, t2, t3 = (bool(t.get(f"target{i}_hit_at")) for i in (1, 2, 3))
        if t1 and entry > cur:
            cur, label = entry, "T1 hit: at cost"
        if t2 and entry * 1.08 > cur:
            cur, label = entry * 1.08, "T2 hit: +8%"
        if t3:
            runner = max(entry * 1.15, entry + max(0.0, high - entry) * 0.70)
            if runner > cur:
                cur, label = runner, "Runner: 70% of peak"
        if not t1 and _f(t.get("option_target1")) > 0:
            nxt = f"at {_f(t.get('option_target1')):.2f} (T1) stop moves to cost {entry:.2f}"
        elif not t2 and _f(t.get("option_target2")) > 0:
            nxt = f"at {_f(t.get('option_target2')):.2f} (T2) stop moves to {entry * 1.08:.2f}"
        elif not t3 and _f(t.get("option_target3")) > 0:
            nxt = f"at {_f(t.get('option_target3')):.2f} (T3) trail starts: 70% of peak gain"
    if lock_mode == "ENFORCE" and entry > 0 and high > 0:
        gain = high / entry - 1.0
        if gain >= 0.10:
            floor = entry * (1.0 + max(0.02, gain - 0.08))
            if floor > cur:
                cur, label = floor, "Profit lock"
    manual = _f(t.get("manual_stop"))
    if manual > cur:
        cur, label = manual, "Manual"
    return {"start_sl": round(start, 2), "cur_sl": round(cur, 2), "sl_label": label, "sl_next": nxt,
            "sl_vs_entry_pct": round((cur / entry - 1.0) * 100.0, 1)}


TYPICAL_ELASTICITY = 24.0          # option % per 1% stock move: median of the journal's response data (22-28) when the contract's own delta is unknown


def stock_needs(t: Mapping[str, Any]) -> dict[str, Any]:
    """How far the STOCK has to move in our favour for the option to gain 10 / 20 / 30% (display only).
    Uses the contract's own elasticity (|delta| x stock price / option price) when the trade has its Greeks, else the typical 24. Time decay is ignored, so
    the real need is a little higher. need10/20/30 are percent moves from the stock's entry price, need10_px/20_px/30_px the matching stock levels."""
    entry, ue = _f(t.get("entry_price")), _f(t.get("underlying_entry"))
    if entry <= 0 or ue <= 0:
        return {}
    delta = _f(t.get("gk_delta"))
    el, src = (abs(delta) * ue / entry if delta else 0.0), "delta"
    if not 5.0 <= el <= 80.0:
        el, src = TYPICAL_ELASTICITY, "typical"
    put = str(t.get("option_type") or "").upper().startswith("P")
    out: dict[str, Any] = {"needs_el": round(el, 1), "needs_src": src}
    for x in (10, 20, 30):
        pct = x / el
        out[f"need{x}"] = round(pct, 2)
        out[f"need{x}_px"] = round(ue * (1.0 - pct / 100.0) if put else ue * (1.0 + pct / 100.0), 2)
    return out

