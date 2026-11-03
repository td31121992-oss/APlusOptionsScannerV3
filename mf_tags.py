"""Money-flow shadow tags at entry (recorded on the candidate / trade; nothing is blocked or re-ranked).

Uses the money-flow module (money_flow.py: net buying minus selling value in Rs crore, per stock and sector, from the order-book recorder's once-a-minute readings). For the
stock and its sector, for the whole session so far and for the last 15 minutes:

    mf_sector                 the sector name the money-flow page uses
    mf_sec_flow_dir           sector flow % (net / traded value) in OUR direction: positive = money moving the way we trade
    mf_sec_flow15_dir         the same for the last 15 minutes (positive = the flow is still with us)
    mf_sec_rank               rank of the sector among sectors with 2+ stocks by flow in our direction (1 = most money moving our way)
    mf_sec_n                  sectors ranked
    mf_sec_net_cr             the sector's net flow, Rs crore (signed as reported, not by direction)
    mf_stock_flow_dir         the stock's own flow % in our direction
    mf_stock_flow15_dir       the same for the last 15 minutes
    mf_stock_rank_in_sector   the stock's rank inside its sector by flow in our direction (1 = the leader)
    mf_aligned                True when the sector's flow is >= ALIGN_PCT in our direction for the session AND the last 15 minutes are not against us

The flow direction comes from the tick rule (a price up-tick counts as buying), so it estimates aggressor direction; it cannot tell institutions from retail.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
ALIGN_PCT = 3.0
CACHE_SECONDS = 45
_cache: dict[int, tuple[float, dict[str, Any]]] = {}


def _sign(direction: str) -> float:
    return 1.0 if str(direction).upper() == "BULLISH" else -1.0


def tags_from_payloads(day: Mapping[str, Any], w15: Mapping[str, Any] | None, symbol: str, direction: str) -> dict[str, Any]:
    try:
        if not day or not day.get("ok"):
            return {}
        sg = _sign(direction)
        sym = str(symbol).upper()
        stocks = {str(s.get("symbol", "")).upper(): s for s in day.get("stocks") or []}
        me = stocks.get(sym)
        if me is None:
            return {}
        sector = str(me.get("sector") or "")
        out: dict[str, Any] = {"mf_sector": sector}
        secs = [s for s in day.get("sectors") or [] if int(s.get("stocks") or 0) >= 2]
        mine = next((s for s in day.get("sectors") or [] if s.get("sector") == sector), None)
        if mine is not None:
            out["mf_sec_flow_dir"] = round(sg * float(mine.get("flow_pct") or 0.0), 2)
            out["mf_sec_net_cr"] = round(float(mine.get("net_cr") or 0.0), 1)
            ranked = sorted(secs, key=lambda s: -sg * float(s.get("flow_pct") or 0.0))
            names = [s.get("sector") for s in ranked]
            if sector in names:
                out["mf_sec_rank"] = names.index(sector) + 1
                out["mf_sec_n"] = len(names)
        out["mf_stock_flow_dir"] = round(sg * float(me.get("flow_pct") or 0.0), 2)
        peers = sorted((s for s in stocks.values() if s.get("sector") == sector), key=lambda s: -sg * float(s.get("flow_pct") or 0.0))
        if peers:
            out["mf_stock_rank_in_sector"] = [str(s.get("symbol", "")).upper() for s in peers].index(sym) + 1
        sec15 = None
        if w15 and w15.get("ok"):
            m15 = next((s for s in w15.get("sectors") or [] if s.get("sector") == sector), None)
            st15 = next((s for s in w15.get("stocks") or [] if str(s.get("symbol", "")).upper() == sym), None)
            if m15 is not None:
                sec15 = sg * float(m15.get("flow_pct") or 0.0)
                out["mf_sec_flow15_dir"] = round(sec15, 2)
            if st15 is not None:
                out["mf_stock_flow15_dir"] = round(sg * float(st15.get("flow_pct") or 0.0), 2)
        if "mf_sec_flow_dir" in out:
            out["mf_aligned"] = bool(out["mf_sec_flow_dir"] >= ALIGN_PCT and (sec15 is None or sec15 >= 0))
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


def _payload(window: int, root: Path) -> dict[str, Any]:
    hit = _cache.get(window)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    import money_flow

    p = money_flow.payload(window=window, root=root)
    _cache[window] = (time.time(), p)
    return p


def mf_tags(symbol: str, direction: str, root: Path = ROOT) -> dict[str, Any]:
    try:
        return tags_from_payloads(_payload(0, root), _payload(15, root), symbol, direction)
    except Exception:                                      # noqa: BLE001
        return {}
