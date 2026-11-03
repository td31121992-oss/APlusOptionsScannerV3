"""Market-breadth gate, SHADOW only: tags a trade with what a breadth rule WOULD have done. Never blocks anything.

Rule under test: a BULLISH (call) trade needs at least MIN_PCT of the F&O stocks up on the day; a BEARISH (put) trade needs
at least MIN_PCT of them down. Exception: the stock itself shows strong evidence going against the market, meaning at least
3 of these 4: moved >= 2% in the trade direction, beating its sector's median by >= 1 point, beyond the previous day's
high (calls) / low (puts), and last-15-minute volume >= 2x normal.
Tag values: PASS (breadth fine), EXCEPTION (breadth bad but strong stock evidence), WOULD_BLOCK, UNKNOWN.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Mapping, Sequence

MIN_PCT = 40.0


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def breadth(rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    up = sum(1 for r in rows if _f(r.get("from_prev_close_pct")) > 0)
    down = sum(1 for r in rows if _f(r.get("from_prev_close_pct")) < 0)
    return up, down


def evaluate(symbol: str, direction: str, rows: Sequence[Mapping[str, Any]], indicators: Mapping[str, Any] | None = None,
             rel_volume_15m: float = 0.0) -> dict[str, Any]:
    up, down = breadth(rows)
    total = up + down
    if total < 20:
        return {"breadth_tag": "UNKNOWN", "breadth_up": up, "breadth_down": down, "breadth_pct_with": 0.0, "breadth_evidence": 0}
    bull = str(direction).upper() == "BULLISH"
    with_pct = (up if bull else down) / total * 100.0
    me = next((r for r in rows if r.get("symbol") == symbol), None)
    evidence = 0
    if me is not None:
        sign = 1.0 if bull else -1.0
        move = _f(me.get("from_prev_close_pct")) * sign
        peers = [_f(r.get("from_prev_close_pct")) for r in rows if r.get("sector") == me.get("sector") and r.get("symbol") != symbol]
        sector_med = median(peers) if len(peers) >= 2 else 0.0
        ind = (indicators or {}).get(symbol) or {}
        ltp = _f(me.get("ltp"))
        beyond = bool(ind.get("pdh") and ltp > _f(ind["pdh"])) if bull else bool(ind.get("pdl") and 0 < ltp < _f(ind["pdl"]))
        evidence = sum([move >= 2.0, move - sector_med * sign >= 1.0, beyond, rel_volume_15m >= 2.0])
    if with_pct >= MIN_PCT:
        tag = "PASS"
    else:
        tag = "EXCEPTION" if evidence >= 3 else "WOULD_BLOCK"
    return {"breadth_tag": tag, "breadth_up": up, "breadth_down": down, "breadth_pct_with": round(with_pct, 1), "breadth_evidence": evidence}
