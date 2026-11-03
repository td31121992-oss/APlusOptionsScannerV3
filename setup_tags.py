"""Breakdown / breakout setup state and market breadth as SHADOW tags (bs_ prefix: recorded on the candidate / trade, never used to allow or block anything).

The setup (research: bearish_scan.py, 11 sessions, 714 bearish signals) is five things together on a 5-minute bar, shown here in OUR direction (a put = the bearish version, a call = the mirror):

    ORB    the bar closes beyond the 30-minute opening range (below its low for a put, above its high for a call)
    VWAP   it closes on our side of the session VWAP
    DL     it makes a fresh day extreme in our direction (day low for a put, day high for a call)
    PDL    it closes beyond the previous day's low (put) / high (call)
    CONF   this bar and the one before both closed beyond that previous-day level by at least CONFIRM_PCT (0.05 %)

    bs_orb, bs_vwap, bs_dl, bs_pdl, bs_confirm     1 / 0 for the LAST completed bar (bs_dl: a fresh extreme in any of the last 3 bars)
    bs_n                                           how many of the five hold now (0-5)
    bs_setup                                       1 when all five hold on the last completed bar
    bs_first_time / bs_first_ago_min               the first bar today at which all five held (the research signal), and minutes since it closed
    bs_since_signal_pct                            price now vs the next bar's open after that first signal, in our direction (positive = already moved our way: chasing)
    bs_breadth_pct                                 share of all F&O stocks on OUR side of their own VWAP right now, 0-100 (from the order-book recorder's average price)
    bs_breadth70                                   1 when that share is 70 % or more: in the research the bearish setup hit its option-style target on 73 % of signals then, 49 % otherwise

Needs the day's 5-minute candles, the previous-day high / low (data/reports/daily_indicators.json) and, for breadth, data/order_book/<day>.csv. Missing pieces just leave their tags blank.
"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
OR_START, OR_END = 9 * 60 + 15, 9 * 60 + 45
CONFIRM_PCT = 0.05
BREADTH_STRONG = 70.0
_IND: dict[str, Any] = {"mtime": None, "data": {}}
_BREADTH: dict[str, Any] = {"day": None, "at": 0.0, "value": None}


def _m(c: Any) -> int:
    return c.timestamp.hour * 60 + c.timestamp.minute


def _levels(root: Path, symbol: str) -> tuple[float, float]:
    path = root / "data" / "reports" / "daily_indicators.json"
    try:
        mtime = path.stat().st_mtime
        if _IND["mtime"] != mtime:
            _IND.update(mtime=mtime, data=json.loads(path.read_text(encoding="utf-8")).get("symbols", {}))
    except (OSError, ValueError):
        return 0.0, 0.0
    d = _IND["data"].get(symbol, {})
    return float(d.get("pdh") or 0), float(d.get("pdl") or 0)


def analyse(candles: Sequence[Any], bull: bool, pdh: float, pdl: float) -> dict[str, Any]:
    """The five conditions on the last completed bar and the first bar at which all five held. Pure; unit tested."""
    cs = [c for c in candles if getattr(c, "close", 0)]
    rng = [c for c in cs if OR_START <= _m(c) < OR_END]
    level = pdh if bull else pdl
    if len(cs) < 8 or len(rng) < 5 or level <= 0:
        return {}
    or_edge = max(float(c.high) for c in rng) if bull else min(float(c.low) for c in rng)
    sign = 1.0 if bull else -1.0
    thresh = level * (1 + sign * CONFIRM_PCT / 100.0)
    cum_pv = cum_v = 0.0
    extreme = None
    fresh: list[bool] = []
    states: list[dict[str, bool]] = []
    first = None
    for i, c in enumerate(cs):
        hi, lo, cl, vol = float(c.high), float(c.low), float(c.close), float(c.volume or 0)
        cum_pv += (hi + lo + cl) / 3.0 * vol
        cum_v += vol
        vwap = cum_pv / cum_v if cum_v > 0 else cl
        px_extreme = hi if bull else lo
        fresh.append(extreme is None or (px_extreme >= extreme if bull else px_extreme <= extreme))
        extreme = px_extreme if extreme is None else (max(extreme, px_extreme) if bull else min(extreme, px_extreme))
        beyond = (lambda v, ref: v > ref) if bull else (lambda v, ref: v < ref)
        conf_now = beyond(cl, thresh) and i > 0 and beyond(float(cs[i - 1].close), thresh)
        s = {"orb": beyond(cl, or_edge), "vwap": beyond(cl, vwap), "dl": any(fresh[-3:]), "pdl": beyond(cl, level), "confirm": conf_now}
        states.append(s)
        if first is None and _m(c) >= OR_END and beyond(cl, or_edge) and beyond(cl, vwap) and fresh[-1] and beyond(cl, level) and conf_now and i < len(cs) - 1:
            first = i
    last = states[-1]
    out: dict[str, Any] = {f"bs_{k}": int(v) for k, v in last.items()}
    out["bs_n"] = sum(1 for v in last.values() if v)
    out["bs_setup"] = int(all(last.values()))
    if first is None and out["bs_setup"] and _m(cs[-1]) >= OR_END:
        first = len(cs) - 1                                # the setup completed on the very last bar: no entry bar yet
    if first is not None:
        t = _m(cs[first]) + 5
        out["bs_first_time"] = f"{t // 60:02d}:{t % 60:02d}"
        out["_first_close_minute"] = t
        entry = float(cs[first + 1].open) if first + 1 < len(cs) else 0.0
        if entry > 0:
            out["bs_since_signal_pct"] = round(sign * (float(cs[-1].close) / entry - 1.0) * 100.0, 2)
    return out


def breadth(root: Path, day: str, bull: bool) -> dict[str, Any]:
    """Share of F&O stocks on our side of their own VWAP (the recorder's average price) at the latest readings; cached 20 s."""
    now = time.time()
    if _BREADTH["day"] != day or now - _BREADTH["at"] > 20:
        value = None
        path = root / "data" / "order_book" / f"{day}.csv"
        try:
            with path.open("rb") as h:
                h.seek(0, 2)
                size = h.tell()
                h.seek(max(0, size - 160_000))
                tail = h.read().decode("utf-8", errors="replace").splitlines()
            h2 = path.open(encoding="utf-8")
            header = next(csv.reader([h2.readline()]))
            h2.close()
            latest: dict[str, tuple[float, float]] = {}
            for row in csv.reader(io.StringIO("\n".join(tail[1:]))):
                if len(row) != len(header):
                    continue
                r = dict(zip(header, row))
                ltp, avg = float(r["ltp"] or 0), float(r["avg_price"] or 0)
                if ltp > 0 and avg > 0:
                    latest[r["symbol"]] = (ltp, avg)
            if len(latest) >= 50:
                value = (sum(1 for a, b in latest.values() if a < b), sum(1 for a, b in latest.values() if a > b), len(latest))
        except (OSError, ValueError, StopIteration):
            value = None
        _BREADTH.update(day=day, at=now, value=value)
    v = _BREADTH["value"]
    if not v:
        return {}
    pct = round(100.0 * (v[1] if bull else v[0]) / v[2], 1)
    return {"bs_breadth_pct": pct, "bs_breadth70": int(pct >= BREADTH_STRONG)}


def setup_tags(symbol: str, candles: Sequence[Any], direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    """Shadow tags for a candidate (see the module docstring). {} when there is not enough data."""
    try:
        bull = str(direction).upper() == "BULLISH"
        pdh, pdl = _levels(root, symbol)
        out = analyse(candles, bull, pdh, pdl)
        first_close = out.pop("_first_close_minute", None)
        if first_close is not None:
            out["bs_first_ago_min"] = max(0, now.hour * 60 + now.minute - first_close)
        out.update(breadth(root, now.date().isoformat(), bull))
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
