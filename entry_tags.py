"""Entry-quality tags (SHADOW only: nothing here blocks or changes a trade).

Candidate entry filters from the Oct 2026 study looked good on the days they were chosen on and failed out-of-sample, so they are only
recorded here, per trade, to be judged on forward data:

  entry_minute        minutes after midnight of the entry (time-of-day bucket)
  entry_premium       option entry price
  f_time_0945         True if the entry is at or after 09:45
  f_premium_5         True if the option premium is >= Rs 5
  f_all               both of the above
  day_regime          market regime at entry (BULL / BEAR / CHOP / UNKNOWN) from market_context, to test a "chop-day" gate
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def evaluate(entry_price: Any, when: datetime, regime: str | None = None) -> dict[str, Any]:
    minute = when.hour * 60 + when.minute
    premium = _f(entry_price)
    t_ok = minute >= 9 * 60 + 45
    p_ok = premium >= 5.0
    return {"entry_minute": minute, "entry_premium": round(premium, 2), "f_time_0945": t_ok, "f_premium_5": p_ok,
            "f_all": bool(t_ok and p_ok), "day_regime": str(regime or "UNKNOWN").upper()}


def regime_of(context: Mapping[str, Any] | None) -> str:
    return str((context or {}).get("regime") or "UNKNOWN").upper()


def entry_context(candles, direction: str, ltp: Any = None) -> dict[str, Any]:
    """SHADOW: how stretched the STOCK already was when we entered, from today's completed 5-minute candles (oldest first).
    "Bought at the top" shows up as: a big move already done from the open, the price sitting at the day's extreme in our direction
    that was set minutes ago, and little or no further progress in the last 15-30 minutes.

      ctx_done_move_pct     move from today's open to now, in our direction
      ctx_range_pos         0..1 position inside the day's range (1.0 = at the high for a call / at the low for a put)
      ctx_mins_since_ext    minutes since the day's extreme in our direction was set
      ctx_last15_pct / ctx_last30_pct   move over the last 15 / 30 minutes, in our direction
      ctx_vs_vwap_pct       distance from the day's VWAP, in our direction
      ctx_at_extreme        range_pos >= 0.9 and the extreme set within 10 minutes
      ctx_fading            at the extreme (or move >= 2% done) while the last 15 minutes made no progress
    """
    try:
        cs = [c for c in candles if getattr(c, "close", 0)]
        if len(cs) < 4:
            return {}
        sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
        o = float(cs[0].open)
        px = float(ltp) if _f(ltp) > 0 else float(cs[-1].close)
        hi = max(float(c.high) for c in cs)
        lo = min(float(c.low) for c in cs)
        rng = hi - lo
        pos = (((px - lo) / rng) if sign > 0 else ((hi - px) / rng)) if rng > 0 else 0.5
        pos = max(0.0, min(1.0, pos))
        ext_price = hi if sign > 0 else lo
        ext_candle = next((c for c in reversed(cs) if (float(c.high) == hi if sign > 0 else float(c.low) == lo)), cs[-1])
        end = cs[-1].timestamp
        mins_since = max(0.0, (end - ext_candle.timestamp).total_seconds() / 60.0) + 5.0       # + the last candle's own length
        c15 = float(cs[-3].close) if len(cs) >= 3 else o
        c30 = float(cs[-6].close) if len(cs) >= 6 else o
        vol = sum(float(c.volume or 0) for c in cs)
        vwap = sum((float(c.high) + float(c.low) + float(c.close)) / 3.0 * float(c.volume or 0) for c in cs) / vol if vol > 0 else px
        done = sign * (px / o - 1.0) * 100.0
        last15 = sign * (px / c15 - 1.0) * 100.0
        ranges = [(float(c.high) - float(c.low)) / float(c.close) * 100.0 for c in cs if float(c.close) > 0]
        vol30 = sum(ranges[-6:]) / len(ranges[-6:])
        vol60 = sum(ranges[-12:]) / len(ranges[-12:])
        # option stop sized to the stock's own recent noise: 2 x the average 5-minute range x 23 (option leverage), kept between 8% and 20%
        vstop30 = max(8.0, min(20.0, 2.0 * vol30 * 23.0))
        vstop60 = max(8.0, min(20.0, 2.0 * vol60 * 23.0))
        at_ext = pos >= 0.9 and mins_since <= 10.0
        return {"ctx_done_move_pct": round(done, 2), "ctx_range_pos": round(pos, 2), "ctx_mins_since_ext": round(mins_since),
                "ctx_last15_pct": round(last15, 2), "ctx_last30_pct": round(sign * (px / c30 - 1.0) * 100.0, 2),
                "ctx_vs_vwap_pct": round(sign * (px / vwap - 1.0) * 100.0, 2), "ctx_at_extreme": bool(at_ext),
                "ctx_fading": bool((at_ext or done >= 2.0) and last15 <= 0.0),
                "ctx_vol30_pct": round(vol30, 3), "ctx_vol60_pct": round(vol60, 3),
                "ctx_vol_stop30_pct": round(vstop30, 1), "ctx_vol_stop60_pct": round(vstop60, 1)}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}


def option_run(candles: Any, entry_price: Any, now: datetime) -> dict[str, Any]:
    """SHADOW: how far the OPTION had already run when we entered, from its own 5-minute candles
    (a dict of arrays as returned by get_intraday_candles: open/high/low/close/timestamp in epoch seconds).

      opt_run15_pct         entry price vs the option's close 15 minutes earlier
      opt_run30_pct         the same over 30 minutes
      opt_run_from_low_pct  entry price vs the option's low of the day so far
      opt_late_guard30      True when the option had already run +30% or more in the last 15 minutes (the guard under test)
      opt_late_guard20      the same at +20%
    """
    try:
        px = _f(entry_price)
        ts = list(candles.get("timestamp") or [])
        cl = [float(x) for x in (candles.get("close") or [])]
        lows = [float(x) for x in (candles.get("low") or [])]
        n = min(len(ts), len(cl), len(lows))
        if px <= 0 or n < 3:
            return {}
        now_ts = now.timestamp()

        def close_before(minutes: int) -> float:
            # last candle that had completely closed `minutes` before now (candle start + 5 min <= now - minutes)
            ref = [cl[i] for i in range(n) if float(ts[i]) + 300 <= now_ts - minutes * 60]
            return ref[-1] if ref else 0.0

        r15, r30 = close_before(15), close_before(30)
        low = min(lows[:n])
        out: dict[str, Any] = {}
        if r15 > 0:
            out["opt_run15_pct"] = round((px / r15 - 1.0) * 100.0, 1)
            out["opt_late_guard30"] = bool(out["opt_run15_pct"] >= 30.0)
            out["opt_late_guard20"] = bool(out["opt_run15_pct"] >= 20.0)
        if r30 > 0:
            out["opt_run30_pct"] = round((px / r30 - 1.0) * 100.0, 1)
        if low > 0:
            out["opt_run_from_low_pct"] = round((px / low - 1.0) * 100.0, 1)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
