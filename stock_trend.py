"""Stock trend gauge, technical indicators and intraday scans for the trade page (READ-ONLY, never changes a trade).

Built from the stock's own candles:
    5M      the last ~6 sessions of 5-minute candles (VWAP is the current day's only)
    15M     the same candles resampled 3:1
    DAILY   about six months of daily candles

Each timeframe returns   {"label", "bullish", "neutral", "bearish", "score" (-1..1), "table": [{name, value, text, tone}]}.
Indicators: ADX(14) with +DI/-DI, MACD(12,26,9), RSI(14), SuperTrend(10,3), ATR(14), VWAP, EMA 5/10/20/50/100/200.
"""

from __future__ import annotations

import math
from typing import Any, Sequence


def _ema(values: Sequence[float], span: int) -> list[float]:
    a = 2.0 / (span + 1.0)
    out: list[float] = []
    e = None
    for v in values:
        e = v if e is None else a * v + (1 - a) * e
        out.append(e)
    return out


def _rma(values: Sequence[float], n: int) -> list[float]:
    out: list[float] = []
    prev = None
    for i, v in enumerate(values):
        if prev is None:
            prev = v
        else:
            prev = (prev * (n - 1) + v) / n
        out.append(prev)
    return out


def _true_range(h, l, c):
    return [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) if i else h[i] - l[i] for i in range(len(c))]


def rsi(c: Sequence[float], n: int = 14) -> float | None:
    if len(c) < n + 2:
        return None
    gains = [max(0.0, c[i] - c[i - 1]) for i in range(1, len(c))]
    losses = [max(0.0, c[i - 1] - c[i]) for i in range(1, len(c))]
    ag, al = _rma(gains, n)[-1], _rma(losses, n)[-1]
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)


def macd(c: Sequence[float]) -> tuple[float, float] | None:
    if len(c) < 35:
        return None
    line = [a - b for a, b in zip(_ema(c, 12), _ema(c, 26))]
    sig = _ema(line, 9)
    return line[-1], sig[-1]


def atr(h, l, c, n: int = 14) -> float | None:
    return _rma(_true_range(h, l, c), n)[-1] if len(c) > n else None


def adx(h, l, c, n: int = 14) -> tuple[float, float, float] | None:
    if len(c) < 2 * n + 2:
        return None
    up = [h[i] - h[i - 1] for i in range(1, len(c))]
    dn = [l[i - 1] - l[i] for i in range(1, len(c))]
    plus = [u if (u > d and u > 0) else 0.0 for u, d in zip(up, dn)]
    minus = [d if (d > u and d > 0) else 0.0 for u, d in zip(up, dn)]
    tr = _true_range(h, l, c)[1:]
    atr_s, p_s, m_s = _rma(tr, n), _rma(plus, n), _rma(minus, n)
    pdi = [100 * p / a if a else 0.0 for p, a in zip(p_s, atr_s)]
    mdi = [100 * m / a if a else 0.0 for m, a in zip(m_s, atr_s)]
    dx = [100 * abs(p - m) / (p + m) if (p + m) else 0.0 for p, m in zip(pdi, mdi)]
    return _rma(dx, n)[-1], pdi[-1], mdi[-1]


def supertrend(h, l, c, n: int = 10, mult: float = 3.0) -> tuple[float, int] | None:
    if len(c) < n + 2:
        return None
    a = _rma(_true_range(h, l, c), n)
    upper = lower = 0.0
    trend = 1
    st = 0.0
    for i in range(len(c)):
        hl2 = (h[i] + l[i]) / 2.0
        bu, bl = hl2 + mult * a[i], hl2 - mult * a[i]
        if i == 0:
            upper, lower = bu, bl
        else:
            upper = bu if (bu < upper or c[i - 1] > upper) else upper
            lower = bl if (bl > lower or c[i - 1] < lower) else lower
            if trend == 1 and c[i] < lower:
                trend = -1
            elif trend == -1 and c[i] > upper:
                trend = 1
        st = lower if trend == 1 else upper
    return st, trend


def _tone(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("bullish", "above", "strong trend", "very strong")):
        return "bull"
    if any(w in t for w in ("bearish", "below", "oversold")):
        return "bear"
    return "neutral"


def analyse(o, h, l, c, v, vwap_from: int, label: str, use_vwap: bool = True) -> dict[str, Any]:
    """o/h/l/c/v are equal-length lists oldest first; vwap_from = index where the current session starts."""
    n = len(c)
    if n < 20:
        return {"label": label, "bullish": 0, "neutral": 0, "bearish": 0, "score": 0.0, "table": [], "note": "not enough candles yet"}
    px = c[-1]
    votes: list[str] = []
    table: list[dict[str, Any]] = []

    def vote(kind: str) -> None:
        votes.append(kind)

    a = adx(h, l, c)
    if a:
        val, pdi, mdi = a
        txt = ("Very Strong Trend" if val >= 50 else "Strong Trend" if val >= 25 else "Trending" if val >= 20 else "Weak / No Trend")
        table.append({"name": "ADX", "value": f"{val:.2f}", "text": txt + (" (up)" if pdi > mdi else " (down)") if val >= 20 else txt,
                      "tone": ("bull" if pdi > mdi else "bear") if val >= 20 else "neutral"})
        vote(("bullish" if pdi > mdi else "bearish") if val >= 20 else "neutral")
    m = macd(c)
    if m:
        line, sig = m
        txt = "Bullish" if line > sig else "Bearish"
        table.append({"name": "MACD", "value": f"{line:.2f}", "text": txt, "tone": "bull" if line > sig else "bear"})
        vote("bullish" if line > sig else "bearish")
    r = rsi(c)
    if r is not None:
        txt = "Overbought" if r >= 70 else "Oversold" if r <= 30 else "Bullish" if r >= 55 else "Bearish" if r <= 45 else "Neutral"
        table.append({"name": "RSI", "value": f"{r:.2f}", "text": txt, "tone": "bull" if r >= 55 else "bear" if r <= 45 else "neutral"})
        vote("bullish" if r >= 55 else "bearish" if r <= 45 else "neutral")
    st = supertrend(h, l, c)
    if st:
        table.append({"name": "SuperTrend", "value": f"{st[0]:.2f}", "text": "Bullish" if st[1] > 0 else "Bearish",
                      "tone": "bull" if st[1] > 0 else "bear"})
        vote("bullish" if st[1] > 0 else "bearish")
    at = atr(h, l, c)
    if at is not None and px > 0:
        pct = at / px * 100.0
        txt = "Low Volatility" if pct < 0.15 else "Medium Volatility" if pct < 0.35 else "High Volatility"
        table.append({"name": "ATR", "value": f"{at:.2f}", "text": txt, "tone": "neutral"})
    if use_vwap and vwap_from < n:
        vol = sum(v[vwap_from:])
        if vol > 0:
            vw = sum(((h[i] + l[i] + c[i]) / 3.0) * v[i] for i in range(vwap_from, n)) / vol
            table.append({"name": "VWAP", "value": f"{vw:.2f}", "text": "Above VWAP" if px >= vw else "Below VWAP",
                          "tone": "bull" if px >= vw else "bear"})
            vote("bullish" if px >= vw else "bearish")
    for span in (5, 10, 20, 50, 100, 200):
        if n >= span + 5:
            e = _ema(c, span)[-1]
            vote("bullish" if px >= e else "bearish")
            if span == 20:
                table.append({"name": "20 EMA", "value": f"{e:.2f}", "text": f"{'Above' if px >= e else 'Below'} 20ema",
                              "tone": "bull" if px >= e else "bear"})
    b, nn, s = votes.count("bullish"), votes.count("neutral"), votes.count("bearish")
    tot = max(1, b + nn + s)
    return {"label": label, "bullish": b, "neutral": nn, "bearish": s, "score": round((b - s) / tot, 3), "table": table}


def resample(o, h, l, c, v, k: int = 3):
    m = len(c) - len(c) % k
    oo, hh, ll, cc, vv = [], [], [], [], []
    # align so the LAST group ends on the latest bar
    start = len(c) - m
    for i in range(start, len(c), k):
        oo.append(o[i])
        hh.append(max(h[i:i + k]))
        ll.append(min(l[i:i + k]))
        cc.append(c[i + k - 1])
        vv.append(sum(v[i:i + k]))
    return oo, hh, ll, cc, vv


def _first_time(bars, pred) -> str:
    """HH:MM of the first of today's 5-minute bars (minute, o, h, l, c) for which pred(o, h, l, c) is true; "" when unknown."""
    for m, o, h, l, c in bars or []:
        try:
            if pred(o, h, l, c):
                return f"{int(m) // 60:02d}:{int(m) % 60:02d}"
        except (TypeError, ValueError):
            continue
    return ""


def scans(ltp: float, open_today: float, high_today: float, low_today: float, prev_close: float, ind: dict[str, Any] | None,
          bull: bool = True, bars=None) -> list[dict[str, str]]:
    """Plain-language intraday scans from daily levels (same wording style as the screener you showed)."""
    out: list[dict[str, str]] = []
    ind = ind or {}

    def f(k):
        try:
            x = float(ind.get(k) or 0)
            return x if x > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    def add(text: str, good: bool, when: str = "") -> None:
        row = {"text": text, "tone": "bull" if good else "bear"}
        if when:
            row["time"] = when
        out.append(row)

    first_bar = _first_time(bars, lambda o, h, l, c: True)

    for key, name in (("ema20", "20 EMA"), ("dma50", "50 DMA"), ("dma100", "100 DMA"), ("dma200", "200 DMA")):
        lvl = f(key)
        if lvl and prev_close:
            if prev_close < lvl <= ltp:
                add(f"{name} Breakout 1D", True, _first_time(bars, lambda o, h, l, c, lv=lvl: h > lv))
            elif prev_close > lvl >= ltp:
                add(f"{name} Breakdown 1D", False, _first_time(bars, lambda o, h, l, c, lv=lvl: l < lv))
    pdh, pdl = f("pdh"), f("pdl")
    if pdh and ltp > pdh:
        add("Above yesterday's high", True, _first_time(bars, lambda o, h, l, c: h > pdh))
    if pdl and ltp < pdl:
        add("Below yesterday's low", False, _first_time(bars, lambda o, h, l, c: l < pdl))
    for key_hi, key_lo, label in (("hi_5d", "lo_5d", "5 Days"), ("hi_10d", "lo_10d", "10 Days"), ("hi_30d", "lo_30d", "30 Days"),
                                  ("hi_90d", "lo_90d", "90 Days")):
        hi, lo = f(key_hi), f(key_lo)
        if hi and ltp > hi:
            add(f"{label} Breakout", True, _first_time(bars, lambda o, h, l, c, v=hi: h > v))
        if lo and ltp < lo:
            add(f"{label} Breakdown", False, _first_time(bars, lambda o, h, l, c, v=lo: l < v))
    h52 = f("hi_52w")
    if h52 and ltp >= h52 * 0.995:
        add("Near 52-week high", True, _first_time(bars, lambda o, h, l, c: c >= h52 * 0.995))
    l52 = f("lo_52w")
    if l52 and ltp <= l52 * 1.005:
        add("Near 52-week low", False, _first_time(bars, lambda o, h, l, c: c <= l52 * 1.005))
    tol = max(0.05, open_today * 0.0005) if open_today else 0
    if open_today and abs(open_today - low_today) <= tol:
        add("Open = Low", True, first_bar)
    if open_today and abs(high_today - open_today) <= tol:
        add("Open = High", False, first_bar)
    if prev_close and open_today:
        gap = (open_today / prev_close - 1.0) * 100.0
        if gap >= 1.0:
            add(f"Gap up {gap:.1f}%", True, first_bar)
        elif gap <= -1.0:
            add(f"Gap down {abs(gap):.1f}%", False, first_bar)
    return out


def build(five: dict[str, list[float]], session_start: int, daily: dict[str, list[float]] | None, ind: dict[str, Any] | None,
          prev_close: float, bull: bool = True) -> dict[str, Any]:
    """five: {o,h,l,c,v} lists of 5-minute bars (multi-day, oldest first); session_start: index of today's first bar."""
    out: dict[str, Any] = {}
    if five and len(five.get("c", [])) >= 20:
        out["5M"] = analyse(five["o"], five["h"], five["l"], five["c"], five["v"], session_start, "5M")
        r15 = resample(five["o"], five["h"], five["l"], five["c"], five["v"], 3)
        # session start for the 15-minute series: the bar count of today's bars divided by 3
        today_bars = len(five["c"]) - session_start
        out["15M"] = analyse(*r15, max(0, len(r15[3]) - max(1, today_bars // 3)), "15M")
    if daily and len(daily.get("c", [])) >= 20:
        out["DAILY"] = analyse(daily["o"], daily["h"], daily["l"], daily["c"], daily["v"], 0, "DAILY", use_vwap=False)
    ltp = five["c"][-1] if five and five.get("c") else 0.0
    if five and five.get("c") and session_start < len(five["c"]):
        o_t = five["o"][session_start]
        h_t = max(five["h"][session_start:])
        l_t = min(five["l"][session_start:])
        mins = five.get("m") or []
        bars = None
        if len(mins) == len(five["c"]):
            bars = [(mins[i], five["o"][i], five["h"][i], five["l"][i], five["c"][i]) for i in range(session_start, len(five["c"]))]
        out["scans"] = scans(ltp, o_t, h_t, l_t, prev_close, ind, bull, bars)
    out["price"] = round(ltp, 2)
    return out


# ----------------------------------------------------------------------------- per-stock helpers (market watch, stock analysis page)
_IND_CACHE: dict[str, Any] = {"mtime": 0.0, "data": {}}


def load_indicators(root) -> dict[str, Any]:
    import json
    from pathlib import Path

    path = Path(root) / "data" / "reports" / "daily_indicators.json"
    try:
        m = path.stat().st_mtime
        if m != _IND_CACHE["mtime"]:
            _IND_CACHE["data"] = json.loads(path.read_text(encoding="utf-8")).get("symbols", {})
            _IND_CACHE["mtime"] = m
    except (OSError, ValueError):
        pass
    return _IND_CACHE["data"]


_TICKS: dict[str, Any] = {"mtime": 0.0, "at": 0.0, "day": "", "data": {}}


def ticks_today(root) -> dict[str, list[tuple[int, float]]]:
    """{symbol: [(minute_of_day, price), ...]} for today from the order-book recorder's per-minute file (no network). Re-read at most
    every 30 seconds; empty when the recorder has not written today's file."""
    import csv
    import time as _time
    from datetime import date, datetime as _dt
    from pathlib import Path

    today = date.today().isoformat()
    path = Path(root) / "data" / "order_book" / f"{today}.csv"
    now = _time.time()
    if _TICKS["day"] == today and now - _TICKS["at"] < 30:
        return _TICKS["data"]
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _TICKS["day"] == today and mtime == _TICKS["mtime"]:
        _TICKS["at"] = now
        return _TICKS["data"]
    out: dict[str, list[tuple[int, float]]] = {}
    last_min: dict[str, int] = {}
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    t = _dt.fromisoformat(row["time"])
                    m = t.hour * 60 + t.minute
                    px = float(row["ltp"])
                except (KeyError, ValueError):
                    continue
                if px <= 0 or m < 555:
                    continue
                s = row.get("symbol") or ""
                if last_min.get(s) == m:                        # one point per minute is enough (the latest of that minute)
                    out[s][-1] = (m, px)
                else:
                    out.setdefault(s, []).append((m, px))
                    last_min[s] = m
    except OSError:
        return _TICKS["data"] if _TICKS["day"] == today else {}
    _TICKS.update({"mtime": mtime, "at": now, "day": today, "data": out})
    return out


def attach_scans(rows: list[dict[str, Any]], root) -> None:
    """Adds `scans` (list of {text, tone, time}) to every market-watch row, from the row's own prices, the daily indicators and
    the order-book recorder's per-minute prices (for the time each scan first triggered). No network."""
    ind = load_indicators(root)
    try:
        ticks = ticks_today(root)
    except Exception:                                      # noqa: BLE001 - times are an extra
        ticks = {}
    for r in rows:
        try:
            sym = str(r.get("symbol") or "").upper()
            ltp = float(r.get("ltp") or 0)
            if ltp <= 0:
                continue
            pts = ticks.get(sym) or []
            bars = [(m, p, p, p, p) for m, p in pts] or None
            r["scans"] = scans(ltp, float(r.get("open_0915") or 0), float(r.get("day_high") or 0), float(r.get("day_low") or 0),
                               float(r.get("previous_close") or 0), ind.get(sym), True, bars)
        except (TypeError, ValueError):
            continue


def for_symbol(symbol: str, root, day: str) -> dict[str, Any]:
    """Full gauge + indicators + scans for one stock (network: cached intraday + daily history)."""
    import trade_chart
    from order_book_recorder import _universe

    symbol = symbol.strip().upper()
    if not trade_chart._UNIVERSE:
        trade_chart._UNIVERSE.update(_universe())
    sid = trade_chart._UNIVERSE.get(symbol)
    if not sid:
        return {"ok": False, "error": "unknown symbol"}
    five, start = trade_chart._five_history(sid, day)
    daily = trade_chart._daily_history(sid, day)
    ind = load_indicators(root).get(symbol)
    prev_close = daily["c"][-1] if daily.get("c") else float((ind or {}).get("last_close") or 0)
    return {"ok": True, "symbol": symbol, "trend": build(five, start, daily, ind, prev_close)}
