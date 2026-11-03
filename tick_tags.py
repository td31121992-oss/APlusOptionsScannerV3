"""Big-print and delta tags from the recorded ticks (SHADOW: recorded on the candidate / trade, never used to allow or block anything).

Reads data/ticks/<day>/<SYMBOL>.csv.gz (tick_recorder.py; every F&O stock from the 22 Oct session, ten stocks before that) up to "now" and computes, in OUR direction
(positive = the tape agrees with the trade: buyers for a call, sellers for a put):

    tk_delta5_dir / tk_delta15_dir / tk_delta30_dir   net aggressor volume (buy - sell) over the last 5 / 15 / 30 minutes, as a share of the volume traded in that window
    tk_delta_accel                                    delta5_dir minus the delta of the 10 minutes before it (positive = the pressure is building our way)
    tk_buy_pct15                                      share of the last 15 minutes' volume tagged buyer-initiated, 0..100 (direction-free)
    tk_big_threshold                                  size of a "big print": the 99th percentile of today's prints so far and at least 3x the median print (needs BIG_MIN_PRINTS prints)
    tk_big_n15                                        big prints in the last 15 minutes
    tk_big_dir15                                      (big buy volume - big sell volume) / their total, in our direction, -1..1 (blank when there were none)
    tk_big_last_dir                                   direction of the most recent big print relative to ours: with / against / ""
    tk_big_last_ago                                   minutes since that print

The buy/sell tag is inferred from the feed (tick_recorder.classify), so treat it as approximate; the closing-auction print (after 15:25) is ignored.
"""

from __future__ import annotations

import csv
import gzip
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
BIG_PCT = 0.99
BIG_MIN_PRINTS = 200
MAX_TIME = 15 * 3600 + 25 * 60            # ignore prints after 15:25 (closing auction)


def _secs(ts: str) -> float | None:
    try:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return None


def read_prints(path: Path) -> list[tuple[float, float, str]]:
    """(seconds of day, quantity, side) for every priced packet; keeps what was read when the file is still being written."""
    out: list[tuple[float, float, str]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                try:
                    q = float(r.get("tq") or 0)
                except ValueError:
                    continue
                t = _secs(r.get("ts", ""))
                side = r.get("side", "")
                if q > 0 and t is not None and t <= MAX_TIME and side in ("B", "S"):
                    out.append((t, q, side))
    except (OSError, EOFError):
        pass
    return out


def tags_from_prints(prints: Sequence[tuple[float, float, str]], direction: str, now_secs: float) -> dict[str, Any]:
    sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
    prints = [p for p in prints if p[0] <= now_secs]
    if len(prints) < 20:
        return {}
    out: dict[str, Any] = {}

    def window(lo_min: float, hi_min: float) -> tuple[float, float]:
        buy = sell = 0.0
        for t, q, side in prints:
            age = (now_secs - t) / 60.0
            if lo_min <= age < hi_min:
                if side == "B":
                    buy += q
                else:
                    sell += q
        return buy, sell

    for name, span in (("tk_delta5_dir", 5), ("tk_delta15_dir", 15), ("tk_delta30_dir", 30)):
        b, s = window(0, span)
        out[name] = round(sign * (b - s) / (b + s), 3) if b + s > 0 else ""
    b5, s5 = window(0, 5)
    bp, sp_ = window(5, 15)
    if b5 + s5 > 0 and bp + sp_ > 0:
        out["tk_delta_accel"] = round(sign * (b5 - s5) / (b5 + s5) - sign * (bp - sp_) / (bp + sp_), 3)
    b15, s15 = window(0, 15)
    if b15 + s15 > 0:
        out["tk_buy_pct15"] = round(100.0 * b15 / (b15 + s15), 1)
    qs = sorted(q for _, q, _ in prints)
    if len(qs) >= BIG_MIN_PRINTS:
        thr = qs[min(len(qs) - 1, int(BIG_PCT * len(qs)))]
        out["tk_big_threshold"] = int(thr)
        floor = 3 * qs[len(qs) // 2]                       # a print must also be well above the typical one (guards against ties at the percentile)
        big = [(t, q, s) for t, q, s in prints if q >= thr and q >= floor]
        recent = [x for x in big if (now_secs - x[0]) / 60.0 < 15]
        out["tk_big_n15"] = len(recent)
        bb = sum(q for _, q, s in recent if s == "B")
        bs = sum(q for _, q, s in recent if s == "S")
        if bb + bs > 0:
            out["tk_big_dir15"] = round(sign * (bb - bs) / (bb + bs), 3)
        if big:
            t, q, s = big[-1]
            agrees = (s == "B") == (sign > 0)
            out["tk_big_last_dir"] = "with" if agrees else "against"
            out["tk_big_last_ago"] = round((now_secs - t) / 60.0, 1)
    return out


def tick_tags(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    try:
        path = root / "data" / "ticks" / now.date().isoformat() / f"{str(symbol).upper()}.csv.gz"
        if not path.exists():
            return {}
        return tags_from_prints(read_prints(path), direction, now.hour * 3600 + now.minute * 60 + now.second)
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
