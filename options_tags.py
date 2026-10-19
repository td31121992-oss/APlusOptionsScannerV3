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
ITM_PCT = 0.5


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
        out.update(contract_tags(snapshot, direction, px))
        import flow_tags

        out.update(flow_tags.gamma_tags(snapshot, direction, px))
        out.update(flow_tags.oi_window_tags(snapshot, direction, px))
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


def contract_tags(snapshot: Any, direction: str, px: float) -> dict[str, Any]:
    """Quality of the option we would buy: the leg about ITM_PCT in the money for our side (as the selector aims for) plus IV rank.

        oc_k_strike / oc_k_ltp     the leg and its price
        oc_k_spread_pct            (ask - bid) / mid, % - cost of getting in and out
        oc_k_vol / oc_k_oi         traded volume and open interest of the leg
        oc_k_oi_chg_pct            OI change today, % of previous OI (fresh positions on this leg)
        oc_k_run_pct               the option's own move since yesterday's close, % (high = already ran, we would be chasing)
        oc_k_delta, oc_k_theta_pct_day, oc_k_move_for_10   from greeks.py: option delta, % of premium lost a day, stock move % for +10% on the option
        oc_iv_rank                 ATM IV against this stock's own recent days, 0..100 (blank until 10 days are recorded; see iv_history.py)
    """
    out: dict[str, Any] = {}
    try:
        bull = str(direction).upper() == "BULLISH"
        want = px * (1.0 - ITM_PCT / 100.0 if bull else 1.0 + ITM_PCT / 100.0)
        cands = [(abs(s.strike - want), s) for s in snapshot.strikes if (s.call if bull else s.put)]
        if not cands:
            return out
        st = min(cands, key=lambda x: x[0])[1]
        leg = st.call if bull else st.put
        ltp = float(getattr(leg, "ltp", 0) or 0)
        bid, ask = float(getattr(leg, "bid", 0) or 0), float(getattr(leg, "ask", 0) or 0)
        out["oc_k_strike"], out["oc_k_ltp"] = st.strike, round(ltp, 2)
        if bid > 0 and ask > 0:
            out["oc_k_spread_pct"] = round((ask - bid) / ((ask + bid) / 2.0) * 100.0, 2)
        out["oc_k_vol"], out["oc_k_oi"] = int(getattr(leg, "volume", 0) or 0), int(getattr(leg, "oi", 0) or 0)
        prev = float(getattr(leg, "previous_oi", 0) or 0)
        if prev > 0:
            out["oc_k_oi_chg_pct"] = round(float(getattr(leg, "oi_change", 0) or 0) / prev * 100.0, 1)
        pc = float(getattr(leg, "previous_close", 0) or 0)
        if pc > 0 and ltp > 0:
            out["oc_k_run_pct"] = round((ltp / pc - 1.0) * 100.0, 1)
        if ltp > 0:
            import greeks

            g = greeks.greeks_at_entry(px, st.strike, getattr(snapshot, "expiry", ""), "CE" if bull else "PE", ltp, float(getattr(leg, "iv", 0) or 0) or None, direction_bull=bull)
            if g:
                out["oc_k_delta"], out["oc_k_theta_pct_day"], out["oc_k_move_for_10"] = g["gk_delta"], g["gk_theta_pct_day"], g["gk_move_pct_to_10pct"]
        iv = float(getattr(snapshot, "atm_iv_hint", 0) or 0)
        atm = min(snapshot.strikes, key=lambda s: abs(s.strike - px))
        civ = float(getattr(atm.call, "iv", 0) or 0) if atm.call else 0.0
        piv = float(getattr(atm.put, "iv", 0) or 0) if atm.put else 0.0
        iv = (civ + piv) / 2.0 if civ > 0 and piv > 0 else iv
        sym = str(getattr(snapshot, "symbol", "") or "")
        if sym and iv > 0:
            import iv_history

            r = iv_history.rank(sym, iv)
            iv_history.record(sym, iv)
            if r is not None:
                out["oc_iv_rank"] = r
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        pass
    return out
