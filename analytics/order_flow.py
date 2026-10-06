"""APlus order-flow analytics for the read-only Stock Analysis tab.

Uses Dhan market-quote depth snapshots plus local 1-minute volume/price history.
The depth snapshot is real order-book information; candle-derived delta is
explicitly labelled a proxy because the current client does not receive
aggressor-side trade classification.
"""

from __future__ import annotations

import math
import time
from typing import Any, Mapping, Sequence


def _num(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _sum_depth(levels: Any) -> float:
    if not isinstance(levels, Sequence) or isinstance(levels, (str, bytes)):
        return 0.0
    total = 0.0
    for level in levels:
        if isinstance(level, Mapping):
            total += max(0.0, _num(level.get("quantity")))
    return total


def _best(levels: Any, *, buy: bool) -> tuple[float, float, int]:
    if not isinstance(levels, Sequence) or isinstance(levels, (str, bytes)):
        return 0.0, 0.0, 0
    rows = [x for x in levels if isinstance(x, Mapping)]
    if not rows:
        return 0.0, 0.0, 0
    if buy:
        row = max(rows, key=lambda x: _num(x.get("price")))
    else:
        row = min(rows, key=lambda x: _num(x.get("price")))
    return (
        _num(row.get("price")),
        max(0.0, _num(row.get("quantity"))),
        int(_num(row.get("orders"), 0)),
    )


def _proxy_delta(points: Sequence[Mapping[str, Any]], lookback: int = 30) -> tuple[float, float, int]:
    """Signed-volume proxy using candle direction; not true aggressor delta."""
    rows = list(points)[-max(1, lookback):]
    delta = 0.0
    total = 0.0
    signed_bars = 0
    previous = 0.0
    for row in rows:
        close = _num(row.get("ltp"))
        volume = max(0.0, _num(row.get("volume")))
        if close <= 0 or volume <= 0:
            previous = close or previous
            continue
        if previous > 0:
            if close > previous:
                delta += volume
                signed_bars += 1
            elif close < previous:
                delta -= volume
                signed_bars += 1
            else:
                # Keep unchanged bars neutral rather than inventing pressure.
                pass
        total += volume
        previous = close
    pct = (delta / total * 100.0) if total else 0.0
    return delta, pct, signed_bars


def _classification(score: float) -> str:
    if score >= 65:
        return "BULLISH"
    if score <= 35:
        return "BEARISH"
    return "BALANCED"


def _event(direction: str, strength: float, *, spread: float, ltp: float, avg: float) -> str:
    if direction == "BULLISH":
        return "AGGRESSIVE BUY PRESSURE" if strength >= 80 else "BUY PRESSURE"
    if direction == "BEARISH":
        return "AGGRESSIVE SELL PRESSURE" if strength <= 20 else "SELL PRESSURE"
    if spread > 0 and ltp > 0 and avg > 0 and abs(ltp - avg) / avg < 0.0004:
        return "BALANCED / ABSORPTION WATCH"
    return "BALANCED"


def build_order_flow(
    *,
    client: Any,
    security_id: str | int,
    segment: str,
    points: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Fetch one read-only depth snapshot and combine it with local history."""
    started = time.monotonic()
    raw = client.get_market_quotes({segment: [int(security_id)]}, mode="quote")
    segment_data = raw.get(segment, {}) if isinstance(raw, Mapping) else {}
    quote = segment_data.get(str(int(security_id))) if isinstance(segment_data, Mapping) else None
    if quote is None and isinstance(segment_data, Mapping):
        quote = segment_data.get(int(security_id))
    if not isinstance(quote, Mapping):
        return {
            "ok": False,
            "data_status": "UNAVAILABLE",
            "error": "Dhan returned no market-depth quote",
        }

    depth = quote.get("depth") if isinstance(quote.get("depth"), Mapping) else {}
    buy_levels = depth.get("buy", [])
    sell_levels = depth.get("sell", [])

    bid_depth = _sum_depth(buy_levels)
    ask_depth = _sum_depth(sell_levels)
    total_book = bid_depth + ask_depth
    book_imbalance = ((bid_depth - ask_depth) / total_book) if total_book else 0.0

    best_bid, best_bid_qty, best_bid_orders = _best(buy_levels, buy=True)
    best_ask, best_ask_qty, best_ask_orders = _best(sell_levels, buy=False)
    spread = max(0.0, best_ask - best_bid) if best_bid and best_ask else 0.0

    ltp = _num(quote.get("last_price"))
    avg_price = _num(quote.get("average_price"))
    last_qty = max(0.0, _num(quote.get("last_quantity")))
    buy_qty = max(0.0, _num(quote.get("buy_quantity")))
    sell_qty = max(0.0, _num(quote.get("sell_quantity")))

    delta, delta_pct, signed_bars = _proxy_delta(points)
    delta_component = max(-1.0, min(1.0, delta_pct / 100.0))
    # Depth is real exchange-book pressure; candle delta is deliberately
    # lower-weighted because it is a direction proxy, not aggressor-tagged flow.
    raw_score = 50.0 + 38.0 * book_imbalance + 22.0 * delta_component
    if avg_price > 0 and ltp > 0:
        raw_score += max(-10.0, min(10.0, (ltp - avg_price) / avg_price * 1000.0))
    score = max(0.0, min(100.0, raw_score))
    direction = _classification(score)

    pending_imbalance = ((buy_qty - sell_qty) / (buy_qty + sell_qty)) if (buy_qty + sell_qty) else 0.0

    return {
        "ok": True,
        "data_status": "LIVE_DEPTH_WITH_CANDLE_DELTA_PROXY",
        "captured_at_epoch": time.time(),
        "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
        "ltp": round(ltp, 2),
        "average_price": round(avg_price, 2),
        "last_quantity": int(last_qty),
        "day_volume": int(max(0.0, _num(quote.get("volume")))),
        "buy_quantity": int(buy_qty),
        "sell_quantity": int(sell_qty),
        "pending_book_imbalance_pct": round(pending_imbalance * 100.0, 2),
        "bid_depth_5": int(bid_depth),
        "ask_depth_5": int(ask_depth),
        "book_imbalance_pct": round(book_imbalance * 100.0, 2),
        "best_bid": round(best_bid, 2),
        "best_bid_qty": int(best_bid_qty),
        "best_bid_orders": best_bid_orders,
        "best_ask": round(best_ask, 2),
        "best_ask_qty": int(best_ask_qty),
        "best_ask_orders": best_ask_orders,
        "spread": round(spread, 4),
        "candle_delta_proxy": int(delta),
        "candle_delta_proxy_pct": round(delta_pct, 2),
        "candle_delta_bars": signed_bars,
        "order_flow_score": round(score, 1),
        "order_flow_bias": direction,
        "event": _event(direction, score, spread=spread, ltp=ltp, avg=avg_price),
        "true_aggressor_delta_available": False,
        "note": "Bid/ask depth is live. Delta is a candle-direction volume proxy until a trade-level aggressor feed is integrated.",
    }
