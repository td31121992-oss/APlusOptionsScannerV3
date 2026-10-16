"""Footprint-lite: 5-minute order-flow candles rebuilt from the recorded ticks (research only).

Reads data/ticks/<day>/<SYMBOL>.csv.gz (tick_recorder.py) and, per 5-minute candle, computes

    open / high / low / close          from the traded prices
    buy_vol / sell_vol / delta         quantity tagged buyer- / seller-initiated, and their difference
    cum_delta                          running delta since the open
    imbalance                          delta / (buy_vol + sell_vol), -1 .. +1
    coth / cotl                        close off the high / low: (high - close) / range and (close - low) / range, 0 .. 1 (the labels on a footprint chart)
    top_bid_depth / top_ask_depth      average best-bid / best-ask quantity during the candle
    packets                            how many feed packets fell inside the candle

    data/ticks/footprint/<day>.csv     one row per symbol per candle
Approximate: a feed packet may bundle several trades and the buy/sell tag is inferred (tick_recorder.py).

    python footprint_lite.py [YYYY-MM-DD ...]
"""

from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
FIELDS = ["day", "symbol", "minute", "time", "open", "high", "low", "close", "buy_vol", "sell_vol", "delta", "cum_delta", "imbalance", "coth", "cotl", "top_bid_depth",
          "top_ask_depth", "packets"]


def _minute(ts: str) -> int | None:
    try:
        h, m = ts.split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def candles_from_ticks(rows: list[dict[str, str]], day: str, symbol: str) -> list[dict[str, Any]]:
    bars: dict[int, dict[str, Any]] = {}
    for r in rows:
        m = _minute(r.get("ts", ""))
        try:
            px = float(r["ltp"])
        except (KeyError, ValueError):
            continue
        if m is None or px <= 0:
            continue
        b0 = (m // 5) * 5
        b = bars.setdefault(b0, {"open": px, "high": px, "low": px, "close": px, "buy": 0, "sell": 0, "bd": 0.0, "ad": 0.0, "n": 0})
        b["high"], b["low"], b["close"] = max(b["high"], px), min(b["low"], px), px
        try:
            tq = int(float(r.get("tq") or 0))
        except ValueError:
            tq = 0
        if tq and r.get("side") == "B":
            b["buy"] += tq
        elif tq and r.get("side") == "S":
            b["sell"] += tq
        b["bd"] += float(r.get("bq") or 0)
        b["ad"] += float(r.get("aq") or 0)
        b["n"] += 1
    out, cum = [], 0
    for b0 in sorted(bars):
        b = bars[b0]
        delta = b["buy"] - b["sell"]
        cum += delta
        rng = b["high"] - b["low"]
        tot = b["buy"] + b["sell"]
        out.append({"day": day, "symbol": symbol, "minute": b0, "time": f"{b0 // 60:02d}:{b0 % 60:02d}", "open": round(b["open"], 2), "high": round(b["high"], 2),
                    "low": round(b["low"], 2), "close": round(b["close"], 2), "buy_vol": b["buy"], "sell_vol": b["sell"], "delta": delta, "cum_delta": cum,
                    "imbalance": round(delta / tot, 3) if tot else 0.0, "coth": round((b["high"] - b["close"]) / rng, 3) if rng > 0 else 0.0,
                    "cotl": round((b["close"] - b["low"]) / rng, 3) if rng > 0 else 0.0, "top_bid_depth": round(b["bd"] / b["n"]) if b["n"] else 0,
                    "top_ask_depth": round(b["ad"] / b["n"]) if b["n"] else 0, "packets": b["n"]})
    return out


def run(day: str, root: Path = ROOT) -> Path | None:
    folder = root / "data" / "ticks" / day
    if not folder.exists():
        return None
    rows: list[dict[str, Any]] = []
    for p in sorted(folder.glob("*.csv.gz")):
        try:
            with gzip.open(p, "rt", encoding="utf-8", newline="") as h:
                ticks = list(csv.DictReader(h))
        except (OSError, EOFError):                        # a file cut off by a crash still gives what was written
            continue
        rows += candles_from_ticks(ticks, day, p.name.split(".")[0])
    if not rows:
        return None
    out = root / "data" / "ticks" / "footprint"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> int:
    import sys

    for d in sys.argv[1:] or [date.today().isoformat()]:
        print(d, run(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
