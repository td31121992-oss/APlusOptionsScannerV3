"""Intraday fields for the technical-alerts tab: VWAP, relative volume, volume breakout, order flow, multi-factor confirmation.

Inputs: the order-book recorder's per-minute file (data/order_book/<date>.csv - latest file is used, so after the close the
tab shows the last session) and the daily indicators (average volume). Everything is read-only.

  vwap_bullish / vwap_bearish   - live price above / below the exchange's day average price
  rvol_spike                    - day volume so far >= 2x the 20-day average pace for this time of day (approximate U-shaped curve)
  volume_breakout_5m            - the last 5 minutes traded >= 3x the average of the earlier 5-minute buckets today
  order_flow_bullish / bearish  - resting buy minus sell quantity (average of the last 5 readings) >= +0.25 / <= -0.25 of the total
  aplus_confirmed               - at least 3 independent confirmations in the same direction (VWAP side, RVOL, order flow,
                                  a 1% move from the open, price in the top/bottom 10% of the day's range)
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, time as clock
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
BOOK_DIR = ROOT / "data" / "order_book"
# cumulative share of a typical day's volume by minutes since 09:15 (approximate)
PROFILE = [(0, 0.0), (15, 0.12), (30, 0.20), (60, 0.32), (120, 0.50), (180, 0.64), (240, 0.78), (300, 0.90), (375, 1.0)]


def expected_fraction(minutes_since_open: float) -> float:
    m = max(0.0, min(375.0, float(minutes_since_open)))
    for (m0, f0), (m1, f1) in zip(PROFILE, PROFILE[1:]):
        if m <= m1:
            return f0 + (f1 - f0) * (m - m0) / (m1 - m0)
    return 1.0


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_book_stats(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Per symbol: last price/avg price/volume, 5-minute volume pace and the recent order-flow imbalance."""
    if path is None:
        files = sorted(BOOK_DIR.glob("*.csv"))
        if not files:
            return {}
        path = files[-1]
    rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for r in csv.DictReader(handle):
                rows[r["symbol"]].append(r)
    except (OSError, KeyError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for symbol, rs in rows.items():
        vols = [_f(r.get("volume")) for r in rs]
        last = rs[-1]
        # volume traded in each 5-reading bucket (readings are about a minute apart)
        buckets = [vols[i] - vols[i - 5] for i in range(5, len(vols), 5) if vols[i] >= vols[i - 5]]
        recent = vols[-1] - vols[-6] if len(vols) >= 6 and vols[-1] >= vols[-6] else 0.0
        earlier = buckets[:-1] if len(buckets) > 1 else []
        imb = [_f(r.get("imbalance")) for r in rs[-5:]]
        try:
            stamp = datetime.fromisoformat(last["time"])
        except (KeyError, ValueError):
            stamp = None
        out[symbol] = {"ltp": _f(last.get("ltp")), "avg_price": _f(last.get("avg_price")), "volume": vols[-1],
                       "recent_5m": recent, "earlier_avg_5m": (sum(earlier) / len(earlier)) if earlier else 0.0,
                       "n_buckets": len(buckets), "imbalance": sum(imb) / len(imb) if imb else 0.0, "time": stamp}
    return out


def enrich_intraday(rows: Sequence[Mapping[str, Any]], stats: Mapping[str, Mapping[str, Any]],
                    indicators: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        r = dict(row)
        sym = str(r.get("symbol", "")).upper()
        s, ind = stats.get(sym) or {}, indicators.get(sym) or {}
        ltp = _f(r.get("ltp")) or _f(s.get("ltp"))
        avg = _f(s.get("avg_price"))
        vwap_up = bool(ltp > 0 and avg > 0 and ltp > avg)
        vwap_dn = bool(ltp > 0 and avg > 0 and ltp < avg)
        rvol = 0.0
        stamp = s.get("time")
        if stamp is not None and _f(ind.get("avg_vol20")) > 0:
            minutes = (stamp.hour * 60 + stamp.minute) - (9 * 60 + 15)
            frac = expected_fraction(minutes)
            if frac > 0.05:
                rvol = _f(s.get("volume")) / (_f(ind["avg_vol20"]) * frac)
        vol_break = bool(s.get("n_buckets", 0) >= 4 and _f(s.get("earlier_avg_5m")) > 0
                         and _f(s.get("recent_5m")) >= 3.0 * _f(s.get("earlier_avg_5m")))
        flow = _f(s.get("imbalance"))
        flow_up, flow_dn = flow >= 0.25, flow <= -0.25
        from_open = _f(r.get("from_open_pct"))
        pos = r.get("range_position_pct")
        pos = _f(pos) if pos not in (None, "") else 50.0
        bull = sum([vwap_up, rvol >= 2.0, flow_up, from_open >= 1.0, pos >= 90.0])
        bear = sum([vwap_dn, rvol >= 2.0, flow_dn, from_open <= -1.0, pos <= 10.0])
        # RVOL counts for the side the price is moving, not both
        if from_open >= 0:
            bear = sum([vwap_dn, flow_dn, from_open <= -1.0, pos <= 10.0])
        else:
            bull = sum([vwap_up, flow_up, from_open >= 1.0, pos >= 90.0])
        r.update({"vwap_bullish": vwap_up, "vwap_bearish": vwap_dn, "rvol": round(rvol, 2), "rvol_spike": rvol >= 2.0,
                  "volume_breakout_5m": vol_break, "order_flow_bullish": flow_up, "order_flow_bearish": flow_dn,
                  "aplus_confirmed": bool(bull >= 3 or bear >= 3)})
        out.append(r)
    return out
