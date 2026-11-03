"""Multi-timeframe context tag (SHADOW / RESEARCH - never blocks or changes a trade).

Asks: does the 5-minute signal agree with the 15-minute trend and with the DAILY trend?

    mtf_15m          UP | DOWN | MIXED   from today's completed 15-minute bars (3 x 5-minute): EMA3 vs EMA8 of the closes and
                                         price vs the day's VWAP; needs at least 3 completed 15-minute bars (09:15-10:00)
    mtf_daily        UP | DOWN | MIXED   price vs the daily EMA20 and 50-day average, and the daily SuperTrend direction
    mtf_daily_score  0-3                 how many of those three daily conditions favour UP
    mtf_agree        0-2                 how many of the two higher timeframes agree with the trade direction
    mtf_all_agree    True when both do
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def _g(c: Any, name: str) -> float:
    try:
        v = c[name] if isinstance(c, Mapping) else getattr(c, name)
        return float(v)
    except (KeyError, AttributeError, TypeError, ValueError):
        return 0.0


def _ema(values: Sequence[float], span: int) -> float:
    a = 2.0 / (span + 1.0)
    e = values[0]
    for v in values[1:]:
        e = a * v + (1 - a) * e
    return e


def resample_15m(candles: Sequence[Any]) -> list[dict[str, float]]:
    """Groups of three consecutive 5-minute candles from the first one of the day; an incomplete trailing group is dropped."""
    cs = [c for c in candles if _g(c, "close") > 0]
    out = []
    for i in range(0, len(cs) - len(cs) % 3, 3):
        g = cs[i:i + 3]
        out.append({"open": _g(g[0], "open"), "high": max(_g(x, "high") for x in g), "low": min(_g(x, "low") for x in g),
                    "close": _g(g[-1], "close"), "volume": sum(_g(x, "volume") for x in g)})
    return out


def mtf_tags(candles: Sequence[Any], direction: str, daily: Mapping[str, Any] | None = None, ltp: float | None = None) -> dict[str, Any]:
    try:
        bull = str(direction).upper() == "BULLISH"
        out: dict[str, Any] = {}
        want = "UP" if bull else "DOWN"
        agree = 0
        bars = resample_15m(candles)
        if len(bars) >= 3:
            closes = [b["close"] for b in bars]
            tp = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars]
            vol = [b["volume"] for b in bars]
            vwap = sum(p * v for p, v in zip(tp, vol)) / sum(vol) if sum(vol) > 0 else closes[-1]
            fast, slow = _ema(closes, 3), _ema(closes, 8)
            px = float(ltp) if ltp and float(ltp) > 0 else closes[-1]
            state = "UP" if (fast > slow and px > vwap) else "DOWN" if (fast < slow and px < vwap) else "MIXED"
            out["mtf_15m"] = state
            agree += int(state == want)
        if daily:
            px = float(ltp) if ltp and float(ltp) > 0 else _g(candles[-1], "close") if candles else 0.0
            score = 0
            known = 0
            for key in ("ema20", "dma50"):
                lvl = daily.get(key)
                if lvl not in (None, "") and float(lvl) > 0 and px > 0:
                    known += 1
                    score += int(px > float(lvl))
            st = daily.get("st_dir")
            if st not in (None, ""):
                known += 1
                score += int(float(st) > 0)
            if known >= 2:
                d = "UP" if score == known else "DOWN" if score == 0 else "MIXED"
                out["mtf_daily"] = d
                out["mtf_daily_score"] = score
                agree += int(d == want)
        if "mtf_15m" in out or "mtf_daily" in out:
            out["mtf_agree"] = agree
            out["mtf_all_agree"] = bool("mtf_15m" in out and "mtf_daily" in out and agree == 2)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
