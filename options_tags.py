"""Option-chain intelligence tags for a trade at entry (SHADOW ONLY - recorded on the trade, never used to allow or block anything).

Built from the option-chain snapshot the scanner already fetched to choose the contract (`analytics.models.OptionChainSnapshot`):

    oc_pcr_oi        put open interest / call open interest, strikes within +-10% of spot
    oc_pcr_vol       the same with traded volume
    oc_atm_iv        average implied volatility of the at-the-money call and put
    oc_iv_skew       ATM put IV minus ATM call IV (positive = puts priced richer)
    oc_call_wall     strike with the most call open interest at or above spot; oc_call_wall_pct = distance from spot in %
    oc_put_wall      strike with the most put open interest at or below spot;  oc_put_wall_pct  = distance from spot in %
    oc_room_pct      distance to the wall in OUR way (calls: call wall above, puts: put wall below)
    oc_wall_close    True when that room is under 1% (the trade runs into the biggest open-interest cluster)
    oc_flow          open-interest change balance in the 5 strikes either side of the money, -1..+1 (positive = put OI added / call OI shed,
                     the bullish reading); oc_flow_aligned = the sign agrees with our direction. Blank when the feed gave no previous OI.
"""

from __future__ import annotations

from typing import Any

BAND_PCT = 10.0
FLOW_STRIKES = 5
WALL_CLOSE_PCT = 1.0


def _oi_total(legs: list[Any], attr: str) -> float:
    return float(sum(max(0.0, float(getattr(x, attr, 0) or 0)) for x in legs))


def chain_tags(snapshot: Any, direction: str, spot: float | None = None) -> dict[str, Any]:
    try:
        strikes = sorted(snapshot.strikes, key=lambda s: s.strike)
        px = float(spot or getattr(snapshot, "underlying_ltp", 0) or 0)
        if not strikes or px <= 0:
            return {}
        near = [s for s in strikes if abs(s.strike / px - 1.0) * 100.0 <= BAND_PCT + 1e-9] or strikes
        calls = [s.call for s in near if s.call]
        puts = [s.put for s in near if s.put]
        out: dict[str, Any] = {}
        co, po = _oi_total(calls, "oi"), _oi_total(puts, "oi")
        cv, pv = _oi_total(calls, "volume"), _oi_total(puts, "volume")
        if co > 0:
            out["oc_pcr_oi"] = round(po / co, 2)
        if cv > 0:
            out["oc_pcr_vol"] = round(pv / cv, 2)
        atm = min(strikes, key=lambda s: abs(s.strike - px))
        civ = float(getattr(atm.call, "iv", 0) or 0) if atm.call else 0.0
        piv = float(getattr(atm.put, "iv", 0) or 0) if atm.put else 0.0
        if civ > 0 and piv > 0:
            out["oc_atm_iv"] = round((civ + piv) / 2.0, 1)
            out["oc_iv_skew"] = round(piv - civ, 1)
        above = [s for s in strikes if s.strike >= px and s.call and (s.call.oi or 0) > 0]
        below = [s for s in strikes if s.strike <= px and s.put and (s.put.oi or 0) > 0]
        if above:
            w = max(above, key=lambda s: s.call.oi)
            out["oc_call_wall"], out["oc_call_wall_pct"] = w.strike, round((w.strike / px - 1.0) * 100.0, 2)
        if below:
            w = max(below, key=lambda s: s.put.oi)
            out["oc_put_wall"], out["oc_put_wall_pct"] = w.strike, round((px / w.strike - 1.0) * 100.0, 2)
        bull = str(direction).upper() == "BULLISH"
        room = out.get("oc_call_wall_pct" if bull else "oc_put_wall_pct")
        if room is not None:
            out["oc_room_pct"] = room
            out["oc_wall_close"] = bool(room < WALL_CLOSE_PCT)
        i = strikes.index(atm)
        band = strikes[max(0, i - FLOW_STRIKES): i + FLOW_STRIKES + 1]
        dc = float(sum(float(getattr(s.call, "oi_change", 0) or 0) for s in band if s.call))
        dp = float(sum(float(getattr(s.put, "oi_change", 0) or 0) for s in band if s.put))
        if (dc or dp) and any((getattr(s.call, "previous_oi", 0) or 0) or (getattr(s.put, "previous_oi", 0) or 0) for s in band):
            flow = (dp - dc) / max(abs(dp) + abs(dc), 1.0)
            out["oc_flow"] = round(flow, 2)
            out["oc_flow_aligned"] = bool(flow > 0.1 if bull else flow < -0.1)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
