"""Sector focus + same-sector stacking rule, SHADOW only: tags a trade with what this rule WOULD have done. Never blocks anything. (Idea of 30 Oct 2026.)

  1. Sector focus until 10:30: trade only the top-2 gaining sectors (calls) / top-2 losing sectors (puts), ranked by the median move from the 09:15 open of the sector's F&O stocks
     (sectors with at least 4 stocks, UNCLASSIFIED left out). Every other sector would not be traded before 10:30. After 10:30 the focus rule does not apply.
       sf_rank / sf_top2_ok / sf_in_window / sf_focus_block;  sf_any_top2 / sf_focus_any_block = the looser reading (sector in either top-2 list, whatever the side).
  2. Stacking: a new call (put) is taken only while the open trades of the same sector and the same side are running in profit; if any of them is not in profit, no new trade.
       sf_stack_n / sf_stack_pnl / sf_stack_block;  looser and stricter readings for comparison: sf_stack_sector_block (same sector, either side), sf_stack_side_block (same side, any sector).
  3. sf_would_block = focus block OR stack block (same sector and same side).
"""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any, Mapping, Sequence

MIN_SECTOR = 4
WINDOW_END_MIN = 10 * 60 + 30
SKIP_SECTORS = {"", "UNCLASSIFIED"}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def sector_order(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Sectors from the best gainer to the worst loser (median move from the 09:15 open)."""
    by: dict[str, list[float]] = {}
    for r in rows:
        m, s = _f(r.get("from_open_pct")), str(r.get("sector") or "")
        if m is not None and s not in SKIP_SECTORS:
            by.setdefault(s, []).append(m)
    meds = {s: median(v) for s, v in by.items() if len(v) >= MIN_SECTOR}
    return sorted(meds, key=lambda k: -meds[k])


def _open_pnl(t: Mapping[str, Any]) -> float:
    entry, mark, qty = _f(t.get("entry_price")), _f(t.get("last_option_price")), _f(t.get("quantity"))
    if not entry or not mark or not qty or entry <= 0 or mark <= 0 or qty <= 0:
        return 0.0
    sell = str(t.get("option_transaction") or t.get("transaction") or "BUY").upper() == "SELL"
    return ((entry - mark) if sell else (mark - entry)) * qty


def evaluate(symbol: str, direction: str, rows: Sequence[Mapping[str, Any]], open_positions: Sequence[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    bull = str(direction).upper() == "BULLISH"
    sec_of = {str(r.get("symbol") or "").upper(): str(r.get("sector") or "") for r in rows}
    my_sector = sec_of.get(str(symbol).upper(), "")
    out: dict[str, Any] = {"sf_sector": my_sector}
    minute = now.hour * 60 + now.minute
    out["sf_in_window"] = bool(minute < WINDOW_END_MIN)

    order = sector_order(rows)
    if my_sector in order:
        side_order = order if bull else order[::-1]
        out["sf_rank"] = side_order.index(my_sector) + 1
        out["sf_top2_ok"] = bool(out["sf_rank"] <= 2)
        out["sf_any_top2"] = bool(my_sector in order[:2] or my_sector in order[-2:])
        out["sf_focus_block"] = bool(out["sf_in_window"] and not out["sf_top2_ok"])
        out["sf_focus_any_block"] = bool(out["sf_in_window"] and not out["sf_any_top2"])

    same_sector_side, same_sector, same_side = [], [], []
    for t in open_positions:
        d = str(t.get("direction") or "").upper()
        s = str(t.get("rgs_sector") or "") or sec_of.get(str(t.get("symbol") or "").upper(), "")
        if my_sector and s == my_sector:
            same_sector.append(t)
            if d == str(direction).upper():
                same_sector_side.append(t)
        if d == str(direction).upper():
            same_side.append(t)
    out["sf_stack_n"] = len(same_sector_side)
    out["sf_stack_pnl"] = round(sum(_open_pnl(t) for t in same_sector_side), 2)
    out["sf_stack_block"] = bool(any(_open_pnl(t) <= 0 for t in same_sector_side))
    out["sf_stack_sector_block"] = bool(any(_open_pnl(t) <= 0 for t in same_sector))
    out["sf_stack_side_block"] = bool(any(_open_pnl(t) <= 0 for t in same_side))
    if "sf_focus_block" in out:
        out["sf_would_block"] = bool(out["sf_focus_block"] or out["sf_stack_block"])
    return out
