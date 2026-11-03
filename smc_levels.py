"""Order blocks and liquidity levels for the charts and for entry tags (DISPLAY + SHADOW only - never blocks or changes a trade).

    zones(candles)        zones for the stock chart canvas:  {"kind": "orderblock", "name", "low", "high", "side": "bull|bear", "state"}
                          and liquidity lines {"kind": "liquidity", "name", "low": p, "high": p, "side": "below|above", "touches": n}
    marks(candles)        the same as plain price-line marks for the trade page (key ob_top / ob_bottom / liq)
    entry_tags(day_candles, direction, ltp)   shadow tags at entry (smc_*)

Order block: the last opposing candle before a strong impulse that breaks the recent range (see order_block.py). It stays "fresh"
while no candle has closed beyond its far side.
Liquidity: where stops are likely resting - two or more swing highs (or lows) within about 0.1% of each other ("equal highs / lows").
The level drawn is the extreme of the cluster, so price has to run through it to take that liquidity.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Sequence

EQUAL_TOL = 0.001            # swing points within 0.1% of each other form one pool
SWING_K = 2
MAX_LEVELS = 3               # per side


def _bars(candles: Sequence[Any]) -> list[SimpleNamespace]:
    out = []
    for c in candles or []:
        try:
            if isinstance(c, dict):
                o, h, l, cl = c.get("o", c.get("open")), c.get("h", c.get("high")), c.get("l", c.get("low")), c.get("c", c.get("close"))
                t = c.get("t", c.get("time"))
            else:
                o, h, l, cl, t = c.open, c.high, c.low, c.close, getattr(c, "t", None)
            o, h, l, cl = float(o), float(h), float(l), float(cl)
        except (AttributeError, TypeError, ValueError):
            continue
        if cl > 0:
            out.append(SimpleNamespace(open=o, high=h, low=l, close=cl, volume=0.0, t=t))
    return out


def _swings(bars: list[SimpleNamespace]) -> tuple[list[int], list[int]]:
    sh, sl = [], []
    for i in range(SWING_K, len(bars) - SWING_K):
        w = bars[i - SWING_K:i + SWING_K + 1]
        if bars[i].high == max(b.high for b in w) and sum(1 for b in w if b.high == bars[i].high) == 1:
            sh.append(i)
        if bars[i].low == min(b.low for b in w) and sum(1 for b in w if b.low == bars[i].low) == 1:
            sl.append(i)
    return sh, sl


def liquidity_levels(candles: Sequence[Any]) -> dict[str, list[dict[str, Any]]]:
    """{"above": [{price, touches}], "below": [...]} - equal highs above price and equal lows below it, nearest first."""
    bars = _bars(candles)
    if len(bars) < 8:
        return {"above": [], "below": []}
    px = bars[-1].close
    sh, sl = _swings(bars)

    def cluster(points: list[float]) -> list[tuple[float, int]]:
        pts = sorted(points)
        groups: list[list[float]] = []
        for p in pts:
            if groups and abs(p / groups[-1][-1] - 1.0) <= EQUAL_TOL:
                groups[-1].append(p)
            else:
                groups.append([p])
        return [(g[-1], len(g)) for g in groups if len(g) >= 2]            # keep only pools with 2+ swing points

    highs = [(p, n) for p, n in cluster([bars[i].high for i in sh]) if p > px]
    lows = [(p, n) for p, n in cluster([bars[i].low for i in sl]) if p < px]
    highs.sort(key=lambda x: x[0] - px)
    lows.sort(key=lambda x: px - x[0])
    # the extreme of the cluster is where the stops sit: lows use the lowest point of the group
    low_levels = []
    for p, n in lows[:MAX_LEVELS]:
        grp = [bars[i].low for i in sl if abs(bars[i].low / p - 1.0) <= EQUAL_TOL * 2]
        low_levels.append({"price": round(min(grp) if grp else p, 2), "touches": n})
    return {"above": [{"price": round(p, 2), "touches": n} for p, n in highs[:MAX_LEVELS]], "below": low_levels}


def order_blocks(candles: Sequence[Any]) -> list[dict[str, Any]]:
    import order_block

    bars = _bars(candles)
    out = []
    if len(bars) < 12:
        return out
    for direction, side in (("BULLISH", "bull"), ("BEARISH", "bear")):
        try:
            r = order_block.order_block_state(bars, direction)
        except Exception:                                  # noqa: BLE001
            continue
        if r.get("state") and r["state"] != "NONE" and r.get("zone_high", 0) > 0:
            out.append({"side": side, "low": float(r["zone_low"]), "high": float(r["zone_high"]), "state": r["state"],
                        "age_bars": int(r.get("age_bars") or 0)})
    return out


def zones(candles: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ob in order_blocks(candles):
        label = ("Bullish" if ob["side"] == "bull" else "Bearish") + f" order block {ob['low']:.2f}-{ob['high']:.2f}"
        out.append({"kind": "orderblock", "name": label, "low": ob["low"], "high": ob["high"], "side": ob["side"],
                    "state": ob["state"], "touches": 0})
    liq = liquidity_levels(candles)
    for side in ("above", "below"):
        for lv in liq[side]:
            out.append({"kind": "liquidity", "name": f"Liquidity {lv['price']:.2f} (equal {'highs' if side == 'above' else 'lows'} x{lv['touches']})",
                        "low": lv["price"], "high": lv["price"], "side": side, "touches": 0})
    return out


def marks(candles: Sequence[Any]) -> list[dict[str, Any]]:
    """Price-line marks for the trade page (it draws lines, not boxes)."""
    out: list[dict[str, Any]] = []
    for ob in order_blocks(candles):
        tag = "Bull OB" if ob["side"] == "bull" else "Bear OB"
        out.append({"key": "ob_top", "name": f"{tag} top", "price": ob["high"], "time": None})
        out.append({"key": "ob_bottom", "name": f"{tag} bottom", "price": ob["low"], "time": None})
    liq = liquidity_levels(candles)
    for side in ("above", "below"):
        for lv in liq[side][:2]:
            out.append({"key": "liq", "name": f"Liquidity x{lv['touches']}", "price": lv["price"], "time": None})
    return out


def entry_tags(candles: Sequence[Any], direction: str, ltp: float | None = None) -> dict[str, Any]:
    """Shadow tags at entry: the order block state for the trade's direction and the nearest liquidity pools, in % from price."""
    try:
        import order_block

        bars = _bars(candles)
        if len(bars) < 12:
            return {}
        px = float(ltp) if ltp and float(ltp) > 0 else bars[-1].close
        bull = str(direction).upper() == "BULLISH"
        ob = order_block.order_block_state(bars, "BULLISH" if bull else "BEARISH")
        out: dict[str, Any] = {"smc_ob_state": ob.get("state", "NONE")}
        if ob.get("state") not in (None, "NONE") and ob.get("zone_high", 0) > 0:
            edge = ob["zone_high"] if bull else ob["zone_low"]
            out["smc_ob_dist_pct"] = round((px / edge - 1.0) * 100.0 * (1 if bull else -1), 2)
            out["smc_ob_age_bars"] = int(ob.get("age_bars") or 0)
        liq = liquidity_levels(bars)
        # "target pool" is the pool the trade is heading into; "stop pool" is the one that sits behind it
        ahead = liq["above"] if bull else liq["below"]
        behind = liq["below"] if bull else liq["above"]
        if ahead:
            out["smc_liq_ahead_pct"] = round(abs(ahead[0]["price"] / px - 1.0) * 100.0, 2)
        if behind:
            out["smc_liq_behind_pct"] = round(abs(behind[0]["price"] / px - 1.0) * 100.0, 2)
        out["smc_liq_pools"] = len(liq["above"]) + len(liq["below"])
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
