"""Live big-print aggregator (DATA ONLY: feeds the Big Players page; never touches the scanner or any trade).

tick_recorder.py hands every tick to a BigPrintTracker. A "big print" is the same thing tick_tags.py uses: a trade quantity at or above the 99th percentile of that stock's prints so far today
AND at least 3x its median print (needs 200 prints first), and worth at least APLUS_BIG_MIN_VALUE rupees (default 10 lakh). Its side (buyer- or seller-initiated) comes from the feed
(tick_recorder.classify). Every 10 seconds the totals are written to

    data/ticks/big_prints_live.json     per stock: big buying / selling in Rs crore today and over the last 15 minutes, counts, the last big print; plus a tape of the latest big prints

This cannot tell an institution from a retail trader or one large order from many split ones: it shows where unusually large aggressive prints are landing, which is where size is pressing.
"""

from __future__ import annotations

import json
import os
import statistics as st
import time
from collections import deque
from pathlib import Path
from typing import Any

CR = 1e7
MIN_PRINTS = 200
WINDOW_S = 15 * 60
WRITE_EVERY = 10.0
KEEP_SIZES = 4000
MAX_TIME = 15 * 3600 + 25 * 60
LAKH = 1e5


def _secs(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _min_value() -> float:
    try:
        return float(os.getenv("APLUS_BIG_MIN_VALUE", "1000000"))
    except ValueError:
        return 1_000_000.0


class _Stock:
    __slots__ = ("sizes", "count", "thr", "buy", "sell", "n_buy", "n_sell", "recent", "last", "ltp")

    def __init__(self) -> None:
        self.sizes: deque[float] = deque(maxlen=KEEP_SIZES)
        self.count = 0
        self.thr = 0.0
        self.buy = self.sell = 0.0
        self.n_buy = self.n_sell = 0
        self.recent: deque[tuple[float, float]] = deque()        # (seconds, signed value)
        self.last: dict[str, Any] | None = None
        self.ltp = 0.0


class BigPrintTracker:
    def __init__(self) -> None:
        self.state: dict[str, _Stock] = {}
        self.tape: deque[dict[str, Any]] = deque(maxlen=60)
        self.min_value = _min_value()
        self._written = 0.0

    def update(self, sym: str, ts: str, ltp: float, tq: float, side: str) -> dict[str, Any] | None:
        """One tick. Returns the big print (dict) when this tick is one."""
        s = self.state.get(sym)
        if s is None:
            s = self.state[sym] = _Stock()
        if ltp > 0:
            s.ltp = ltp
        if tq <= 0 or side not in ("B", "S") or ltp <= 0:
            return None
        t = _secs(ts)
        if t > MAX_TIME:
            return None
        s.sizes.append(tq)
        s.count += 1
        if s.count >= MIN_PRINTS and s.count % 50 == 0:
            qs = sorted(s.sizes)
            s.thr = max(qs[min(len(qs) - 1, int(0.99 * len(qs)))], 3 * st.median(qs))
        if s.thr <= 0 or tq < s.thr or tq * ltp < self.min_value:
            return None
        value = tq * ltp
        if side == "B":
            s.buy += value
            s.n_buy += 1
        else:
            s.sell += value
            s.n_sell += 1
        s.recent.append((t, value if side == "B" else -value))
        ev = {"t": ts[:8], "s": sym, "side": side, "qty": int(tq), "px": round(ltp, 2), "lakh": round(value / LAKH, 1)}
        s.last = ev
        self.tape.append(ev)
        return ev

    def snapshot(self, now_s: float) -> dict[str, Any]:
        stocks: dict[str, Any] = {}
        for sym, s in self.state.items():
            while s.recent and now_s - s.recent[0][0] > WINDOW_S:
                s.recent.popleft()
            n15 = sum(v for _t, v in s.recent)
            stocks[sym] = {"ltp": round(s.ltp, 2), "buy_cr": round(s.buy / CR, 2), "sell_cr": round(s.sell / CR, 2), "net_cr": round((s.buy - s.sell) / CR, 2),
                           "n_buy": s.n_buy, "n_sell": s.n_sell, "net15_cr": round(n15 / CR, 2), "n15": len(s.recent), "thr_qty": int(s.thr), "last": s.last}
        return {"stocks": stocks, "tape": list(self.tape)}

    def maybe_write(self, root: Path, day: str, now_s: float, force: bool = False) -> bool:
        if not force and time.monotonic() - self._written < WRITE_EVERY:
            return False
        self._written = time.monotonic()
        snap = self.snapshot(now_s)
        snap.update(day=day, updated=f"{int(now_s // 3600):02d}:{int(now_s % 3600 // 60):02d}:{int(now_s % 60):02d}")
        path = root / "data" / "ticks" / "big_prints_live.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            return False
        return True


_CACHE: dict[str, Any] = {"mtime": None, "data": None}


def load(root: Path, day: str) -> dict[str, Any] | None:
    """The latest written snapshot for `day`, or None (cached by modification time)."""
    path = root / "data" / "ticks" / "big_prints_live.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _CACHE["mtime"] != mtime:
        try:
            _CACHE.update(mtime=mtime, data=json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None
    d = _CACHE["data"]
    return d if d and d.get("day") == day else None


def replay(day: str, root: Path, symbols: list[str] | None = None, upto: str = "15:25:00") -> BigPrintTracker:
    """Run the tracker over a recorded day (data/ticks/<day>/*.csv.gz) up to `upto` (for tests and checks; the live recorder feeds ticks one at a time)."""
    import csv
    import gzip

    tr = BigPrintTracker()
    for path in sorted((root / "data" / "ticks" / day).glob("*.csv.gz")):
        sym = path.name[: -len(".csv.gz")]
        if symbols and sym not in symbols:
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as h:
                for r in csv.DictReader(h):
                    if r["ts"] > upto:
                        break
                    try:
                        tr.update(sym, r["ts"], float(r["ltp"]), float(r["tq"] or 0), r["side"])
                    except (KeyError, ValueError):
                        continue
        except (OSError, EOFError):
            continue
    return tr
