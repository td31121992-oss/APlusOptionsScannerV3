"""Sector priority as SHADOW tags (recorded on the candidate / trade; nothing is blocked or re-ranked yet).

Idea: if most stocks of a stock's sector are already moving the same way (say 6-7 of 10 IT stocks up since the open), a trade in that sector deserves more weight than one in a sector
that is split or going the other way - as a 20-25% weighting in the ranking, not a hard filter.

    sp_sector     the finer sector group (sector_groups.fine_sector)
    sp_peers      peers counted (the sector's other F&O stocks with a price)
    sp_frac       share of peers up (call) / down (put) by more than MOVE_PCT since the open, 0..1
    sp_avg        average peer move since the open, in OUR direction, %
    sp_score      0..100 = 100 x sp_frac (the number a 20-25% weight would use)
    sp_leader     True when sp_frac >= LEADER_FRAC (the sector is clearly moving our way)

9-day history (signals with 4+ peers): hit-before-stop 62% / stopped first 19% when 80%+ of peers moved our way (130 signals); 51-56% / 24-33% otherwise. Small, so tags first.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

MOVE_PCT = 0.5
MIN_PEERS = 4
LEADER_FRAC = 0.7


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def sector_tags(rows: Iterable[Mapping[str, Any]], symbol: str, direction: str) -> dict[str, Any]:
    try:
        import sector_groups

        rows = list(rows or [])
        me = next((r for r in rows if str(r.get("symbol") or "").upper() == str(symbol).upper()), None)
        if me is None:
            return {}
        sector = sector_groups.fine_sector(str(me.get("symbol")), str(me.get("sector") or ""))
        sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
        moves = []
        for r in rows:
            if str(r.get("symbol") or "").upper() == str(symbol).upper():
                continue
            if sector_groups.fine_sector(str(r.get("symbol")), str(r.get("sector") or "")) != sector:
                continue
            mv = _f(r.get("from_open_pct"))
            if mv is not None:
                moves.append(sign * mv)
        if len(moves) < MIN_PEERS:
            return {"sp_sector": sector, "sp_peers": len(moves)}
        frac = sum(1 for m in moves if m > MOVE_PCT) / len(moves)
        return {"sp_sector": sector, "sp_peers": len(moves), "sp_frac": round(frac, 2), "sp_avg": round(sum(moves) / len(moves), 2),
                "sp_score": round(100.0 * frac, 0), "sp_leader": bool(frac >= LEADER_FRAC)}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
