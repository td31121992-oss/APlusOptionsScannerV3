"""Independent read-only volume-profile and footprint analytics.

OHLCV-derived profiles are estimates because candles do not reveal traded volume at
each price. Footprint metrics require supplied bid/ask-at-price volume.
"""
from __future__ import annotations
from collections import defaultdict
from math import isfinite
from typing import Any, Iterable

def _number(row: dict[str, Any], key: str) -> float | None:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if isfinite(value) else None

def build_volume_profile(candles: Iterable[dict[str, Any]], *, tick_size: float = 0.05,
                         value_area_fraction: float = 0.70, max_bins: int = 200) -> dict[str, Any]:
    """Estimate price-volume profile by spreading each candle's volume uniformly across its range."""
    if not isfinite(tick_size) or tick_size <= 0:
        raise ValueError("tick_size must be finite and > 0")
    if not 0 < value_area_fraction <= 1:
        raise ValueError("value_area_fraction must be in (0, 1]")
    if max_bins < 3:
        raise ValueError("max_bins must be >= 3")
    valid = []
    for row in candles:
        low, high, volume, close = (_number(row, k) for k in ("low", "high", "volume", "close"))
        if None in (low, high, volume, close) or low < 0 or high < low or volume < 0:
            continue
        valid.append((low, high, close, volume))
    if not valid or sum(r[3] for r in valid) <= 0:
        return {"ok": False, "reason": "no_valid_positive_volume_candles"}
    min_price, max_price = min(r[0] for r in valid), max(r[1] for r in valid)
    step = tick_size
    count = int((max_price - min_price) / step) + 1
    if count > max_bins:
        step, count = (max_price - min_price) / (max_bins - 1), max_bins
    profile = defaultdict(float)
    for low, high, close, volume in valid:
        lo = max(0, min(count - 1, int((low - min_price) / step)))
        hi = max(lo, min(count - 1, int((high - min_price) / step)))
        share = volume / (hi - lo + 1)
        for idx in range(lo, hi + 1):
            profile[idx] += share
    total = sum(profile.values())
    poc = max(profile, key=profile.get)
    included, accumulated = {poc}, profile[poc]
    left, right = poc - 1, poc + 1
    while accumulated < total * value_area_fraction and (left >= 0 or right < count):
        lv = profile.get(left, 0.0) if left >= 0 else -1.0
        rv = profile.get(right, 0.0) if right < count else -1.0
        if lv >= rv and left >= 0:
            included.add(left); accumulated += max(0.0, lv); left -= 1
        elif right < count:
            included.add(right); accumulated += max(0.0, rv); right += 1
        elif left >= 0:
            included.add(left); accumulated += max(0.0, lv); left -= 1
    price = lambda i: round(min_price + i * step, 6)
    ordered = sorted(profile.items())
    avg = total / max(1, len(profile))
    return {
        "ok": True, "analysis_mode": "READ_ONLY",
        "profile_method": "OHLCV_RANGE_UNIFORM_ESTIMATE", "is_true_trade_at_price_profile": False,
        "tick_size_used": round(step, 8), "total_volume_allocated": round(total, 4),
        "poc": price(poc), "vah": price(max(included)), "val": price(min(included)),
        "value_area_fraction_target": value_area_fraction,
        "high_volume_nodes": [price(i) for i, v in ordered if v >= avg * 1.5][:10],
        "low_volume_nodes": [price(i) for i, v in ordered if v <= avg * 0.5][:10],
        "profile": [{"price": price(i), "estimated_volume": round(v, 4)} for i, v in ordered],
        "notes": [
            "Candle volume is spread uniformly across each candle range; intrabar volume distribution is unknown.",
            "POC/VAH/VAL and HVN/LVN are descriptive estimates, not guaranteed support/resistance or trade signals.",
            "No trading decisions, eligibility changes, or order actions are produced."
        ]
    }

def analyze_footprint(levels: Iterable[dict[str, Any]], *, imbalance_ratio: float = 3.0,
                      min_side_volume: float = 1.0) -> dict[str, Any]:
    """Analyze supplied bid/ask volume per price; never infer aggressor side from candles."""
    if not isfinite(imbalance_ratio) or imbalance_ratio <= 1:
        raise ValueError("imbalance_ratio must be finite and > 1")
    if not isfinite(min_side_volume) or min_side_volume < 0:
        raise ValueError("min_side_volume must be finite and >= 0")
    aggregate = defaultdict(lambda: [0.0, 0.0])
    for row in levels:
        price, bid, ask = (_number(row, k) for k in ("price", "bid_volume", "ask_volume"))
        if None in (price, bid, ask) or price < 0 or bid < 0 or ask < 0:
            continue
        aggregate[price][0] += bid
        aggregate[price][1] += ask
    if not aggregate:
        return {"ok": False, "analysis_mode": "READ_ONLY",
                "reason": "bid_ask_volume_by_price_unavailable",
                "required_fields": ["price", "bid_volume", "ask_volume"],
                "notes": ["OHLCV candles alone cannot reconstruct true footprint bid/ask volume."]}
    rows = []
    for price, (bid, ask) in sorted(aggregate.items()):
        rows.append({"price": price, "bid_volume": round(bid, 4), "ask_volume": round(ask, 4),
                     "delta": round(ask - bid, 4), "total_volume": round(bid + ask, 4),
                     "imbalance": "BUY" if ask >= max(min_side_volume, bid * imbalance_ratio) else
                                  "SELL" if bid >= max(min_side_volume, ask * imbalance_ratio) else "NONE"})
    bid_total, ask_total = sum(r["bid_volume"] for r in rows), sum(r["ask_volume"] for r in rows)
    total = bid_total + ask_total
    return {
        "ok": True, "analysis_mode": "READ_ONLY", "data_basis": "SUPPLIED_BID_ASK_VOLUME_BY_PRICE",
        "bid_volume": round(bid_total, 4), "ask_volume": round(ask_total, 4),
        "delta": round(ask_total - bid_total, 4),
        "delta_percent": round(100 * (ask_total - bid_total) / total, 3) if total else 0.0,
        "levels": rows, "stacked_imbalances": {"buy": _stacked(rows, "BUY"), "sell": _stacked(rows, "SELL")},
        "notes": [
            "Delta and imbalances depend on the upstream feed's bid/ask aggressor classification.",
            "Absorption and exhaustion require time-sequenced trades and price response; they are not asserted from one snapshot.",
            "Read-only: no trade decision or order action is produced."
        ]
    }

def _stacked(rows: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    runs, current = [], []
    for row in rows:
        if row["imbalance"] == side:
            current.append(row)
        else:
            if len(current) >= 3:
                runs.append(current)
            current = []
    if len(current) >= 3:
        runs.append(current)
    return [{"side": side, "from_price": run[0]["price"], "to_price": run[-1]["price"],
             "levels": len(run)} for run in runs]
