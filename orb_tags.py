"""30-minute opening-range breakout / retest as SHADOW tags at entry (recorded on the candidate / trade, never used to allow or block anything).

The range is the high / low of the 09:15-09:44 five-minute bars. After 09:45 the first 5-minute CLOSE outside it is the breakout; a later bar that touches back to the
broken edge and closes outside it again is the retest (within RETEST_BARS bars). Research on 10 days (3,272 events): breakouts hit +10% before -20% on 59% of signals
against a 54% baseline, but 52% once the two big down days (8 and 21 Oct) are removed, so this is recorded, not used.

    orb_state          FORMING (before 09:45) / INSIDE / ABOVE / BELOW  - where the stock last closed relative to the range
    orb_with           with / against / inside  - relative to OUR direction (a call is "with" above the range, a put below it)
    orb_range_pct      width of the opening range, % of the open
    orb_break_dir      BULLISH / BEARISH / ""   - direction of the first close outside the range
    orb_break_time     HH:MM the breakout bar closed
    orb_mins_since     minutes since the breakout
    orb_break_vol_x    breakout bar volume / average volume of the six range bars
    orb_retested       True when the retest has happened
    orb_dist_edge_pct  distance of the last close from the nearer range edge in our direction, % (positive = beyond the edge the way we trade)
"""

from __future__ import annotations

from typing import Any, Sequence

RANGE_START, RANGE_END = 9 * 60 + 15, 9 * 60 + 45
RETEST_BARS = 12


def _m(c: Any) -> int:
    return c.timestamp.hour * 60 + c.timestamp.minute


def orb_tags(candles: Sequence[Any], direction: str) -> dict[str, Any]:
    try:
        cs = [c for c in candles if getattr(c, "close", 0)]
        if len(cs) < 2:
            return {}
        bull = str(direction).upper() == "BULLISH"
        sign = 1.0 if bull else -1.0
        rng = [c for c in cs if RANGE_START <= _m(c) < RANGE_END]
        last = cs[-1]
        if _m(last) < RANGE_END - 5 or len(rng) < 5:
            return {"orb_state": "FORMING"}
        orh, orl = max(float(c.high) for c in rng), min(float(c.low) for c in rng)
        base = float(rng[0].open)
        if base <= 0 or orh <= orl:
            return {}
        avgv = sum(float(c.volume or 0) for c in rng) / len(rng) or 1.0
        out: dict[str, Any] = {"orb_range_pct": round((orh - orl) / base * 100.0, 2)}
        px = float(last.close)
        state = "ABOVE" if px > orh else ("BELOW" if px < orl else "INSIDE")
        out["orb_state"] = state
        out["orb_with"] = "inside" if state == "INSIDE" else ("with" if (state == "ABOVE") == bull else "against")
        edge = orh if bull else orl
        out["orb_dist_edge_pct"] = round(sign * (px - edge) / base * 100.0, 2)
        after = [c for c in cs if _m(c) >= RANGE_END]
        brk = None
        for i, c in enumerate(after):
            cl = float(c.close)
            if cl > orh or cl < orl:
                brk = i
                break
        if brk is not None:
            c = after[brk]
            bdir = "BULLISH" if float(c.close) > orh else "BEARISH"
            bedge = orh if bdir == "BULLISH" else orl
            end_min = _m(c) + 5
            out["orb_break_dir"] = bdir
            out["orb_break_time"] = f"{end_min // 60:02d}:{end_min % 60:02d}"
            out["orb_mins_since"] = max(0, _m(last) + 5 - end_min)
            out["orb_break_vol_x"] = round(float(c.volume or 0) / avgv, 2)
            retest = False
            for r in after[brk + 1: brk + 1 + RETEST_BARS]:
                touched = float(r.low) <= bedge if bdir == "BULLISH" else float(r.high) >= bedge
                closed_out = float(r.close) > bedge if bdir == "BULLISH" else float(r.close) < bedge
                if touched and closed_out:
                    retest = True
                    break
            out["orb_retested"] = retest
        else:
            out["orb_break_dir"] = ""
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
