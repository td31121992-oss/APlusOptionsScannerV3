"""Regime + sector gate, SHADOW only: tags a trade with what this rule WOULD have done. Never blocks anything. (Idea of 29 Oct 2026; separate from breadth_gate.py.)

  1. Market regime: of the F&O stocks with a price, more above yesterday's close than below -> only CALLS are allowed; more below than above -> only PUTS (rgs_regime_ok).
     rgs_regime60_ok is the stricter form: the majority side must hold more than 60% of the stocks.
  2. Sector: the sector with the highest median move (calls) / lowest (puts) is the only sector allowed (rgs_sector1_ok); rgs_sector2_ok allows the best two. Stocks of every other sector would not be traded.
  3. rgs_would_block = the entry fails the regime rule OR the stock is not in the top-1 sector. rgs_regime_block = fails the regime rule alone (to see what the sector part adds).

Backtest (regime_sector_backtest.py, 1,235 days, 210 stocks, Jul 2021 - Aug 2026, top-3 movers, after 0.25% option cost): the regime rule gained about +0.1% gross to the close and the sector part added nothing on top of it;
no variant paid the cost (best -0.10% after cost). The forward shadow data decides.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Mapping, Sequence

MIN_STOCKS = 20
MIN_SECTOR = 4


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def sector_medians(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    by: dict[str, list[float]] = {}
    for r in rows:
        m, s = _f(r.get("from_prev_close_pct")), str(r.get("sector") or "")
        if m is not None and s:
            by.setdefault(s, []).append(m)
    return {s: median(v) for s, v in by.items() if len(v) >= MIN_SECTOR}


def evaluate(symbol: str, direction: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    moves = [m for m in (_f(r.get("from_prev_close_pct")) for r in rows) if m is not None]
    up, down = sum(1 for m in moves if m > 0), sum(1 for m in moves if m < 0)
    total = up + down
    if total < MIN_STOCKS:
        return {"rgs_regime": "UNKNOWN"}
    bull = str(direction).upper() == "BULLISH"
    share_up = up / total * 100.0
    regime = "UP" if up > down else ("DOWN" if down > up else "SPLIT")
    with_share = share_up if bull else 100.0 - share_up
    meds = sector_medians(rows)
    me = next((r for r in rows if r.get("symbol") == symbol), None)
    my_sector = str((me or {}).get("sector") or "")
    out: dict[str, Any] = {"rgs_regime": regime, "rgs_up_pct": round(share_up, 1), "rgs_sector": my_sector}
    regime_ok = (up > down) if bull else (down > up)
    out["rgs_regime_ok"] = bool(regime_ok)
    out["rgs_regime60_ok"] = bool(with_share > 60.0)
    if meds and my_sector in meds:
        order = sorted(meds, key=lambda k: -meds[k] * (1 if bull else -1))
        out["rgs_top_sector"] = order[0]
        out["rgs_sector_rank"] = order.index(my_sector) + 1
        out["rgs_sector1_ok"] = bool(order.index(my_sector) < 1)
        out["rgs_sector2_ok"] = bool(order.index(my_sector) < 2)
        out["rgs_would_block"] = bool(not (regime_ok and out["rgs_sector1_ok"]))
    out["rgs_regime_block"] = bool(not regime_ok)
    return out
