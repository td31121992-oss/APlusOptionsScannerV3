"""Tick-driven burst detector (SHADOW: it records events and tags candidates; it never allows, blocks or places anything).

The scanner decides once a minute, so a move that explodes in a few minutes is first seen late. This watches every recorded tick (tick_recorder.py feeds it each packet) and fires within
seconds when a stock's price moves with a sudden volume surge and aggressor flow on one side:

    price moved   at least MOVE_PCT in the last WINDOW_S seconds (default 0.25 % in 120 s)
    volume surge  volume in that window at least VOLX (default 3) x the stock's usual volume for a window that long (average of the previous 20 minutes)
    flow agrees   buyer-initiated share of that volume >= BUY_SHARE for an up move, <= 1 - BUY_SHARE for a down move (default 0.65)
    quiet period  09:20 - 15:00 only, at most one event per stock and direction every COOLDOWN_MIN minutes (default 10)

    data/tick_events/<day>.csv     one row per event (columns in FIELDS)
    event_tags(symbol, direction, now)   shadow tags for a candidate:  td_fired (an event for this stock in the last 15 minutes), td_aligned (its direction matches the trade),
                                         td_ago_min, td_volx, td_move_pct, td_buy_share, td_n_today
    python tick_detector.py --replay 2026-10-22 [--symbols POLICYBZR,KALYANKJIL]    run the detector over a recorded day and list the events (nothing is written)

Settings: APLUS_TD_WINDOW_S, APLUS_TD_MOVE_PCT, APLUS_TD_VOLX, APLUS_TD_BUY_SHARE, APLUS_TD_COOLDOWN_MIN, APLUS_TD_MIN_BASE_MIN (8), APLUS_TICK_DETECTOR=0 turns the live feed off.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent
FIELDS = ["time", "symbol", "direction", "ltp", "move_pct", "volx", "buy_share", "vol_window", "base_window", "day_move_pct"]
FIRST, LAST = 9 * 3600 + 20 * 60, 15 * 3600


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def enabled() -> bool:
    return os.getenv("APLUS_TICK_DETECTOR", "1").strip() != "0"


def seconds(ts: str) -> float:
    """'10:07:31.250' -> seconds since midnight."""
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


class _Stock:
    __slots__ = ("win", "vol", "buy", "minutes", "first_min", "open", "last_fire", "cur_min", "cur_vol")

    def __init__(self) -> None:
        self.win: deque[tuple[float, float, float, int]] = deque()      # (t, ltp, traded qty, +1 buy / -1 sell / 0 unknown)
        self.vol = 0.0
        self.buy = 0.0
        self.minutes: deque[float] = deque(maxlen=20)                    # volumes of the last completed minutes
        self.first_min: int | None = None
        self.open = 0.0
        self.last_fire: dict[str, float] = {}
        self.cur_min: int | None = None
        self.cur_vol = 0.0


class TickDetector:
    def __init__(self) -> None:
        self.window = _num("APLUS_TD_WINDOW_S", 120)
        self.move_pct = _num("APLUS_TD_MOVE_PCT", 0.25)
        self.volx = _num("APLUS_TD_VOLX", 3.0)
        self.buy_share = _num("APLUS_TD_BUY_SHARE", 0.65)
        self.cooldown = _num("APLUS_TD_COOLDOWN_MIN", 10) * 60
        self.min_base = int(_num("APLUS_TD_MIN_BASE_MIN", 8))
        self.state: dict[str, _Stock] = {}

    def update(self, sym: str, ts: str, ltp: float, tq: float, side: str) -> dict[str, Any] | None:
        """One tick. Returns an event dict when the burst conditions are met, else None."""
        t = seconds(ts)
        s = self.state.get(sym)
        if s is None:
            s = self.state[sym] = _Stock()
        if ltp <= 0:
            return None
        if not s.open:
            s.open = ltp
        minute = int(t // 60)
        if s.first_min is None:
            s.first_min = minute
        if s.cur_min is None:
            s.cur_min = minute
        while s.cur_min < minute:                                         # close finished minutes (a minute with no ticks counts as zero volume)
            s.minutes.append(s.cur_vol)
            s.cur_vol = 0.0
            s.cur_min += 1
        sign = 1 if side == "B" else -1 if side == "S" else 0
        qty = float(tq) if tq else 0.0
        s.win.append((t, ltp, qty, sign))
        s.vol += qty
        if sign > 0:
            s.buy += qty
        s.cur_vol += qty
        while s.win and t - s.win[0][0] > self.window:
            _t, _p, q, sg = s.win.popleft()
            s.vol -= q
            if sg > 0:
                s.buy -= q
        if qty <= 0 or not FIRST <= t <= LAST or len(s.minutes) < self.min_base or t - s.win[0][0] < 30:
            return None
        base_minute = sum(s.minutes) / len(s.minutes)
        base_window = base_minute * self.window / 60.0
        if base_window <= 0 or s.vol <= 0:
            return None
        volx = s.vol / base_window
        if volx < self.volx:
            return None
        move = (ltp / s.win[0][1] - 1.0) * 100.0
        if abs(move) < self.move_pct:
            return None
        share = s.buy / s.vol
        up = move > 0
        if (up and share < self.buy_share) or (not up and share > 1.0 - self.buy_share):
            return None
        direction = "BULLISH" if up else "BEARISH"
        if t - s.last_fire.get(direction, -1e9) < self.cooldown:
            return None
        s.last_fire[direction] = t
        return {"time": ts[:8], "symbol": sym, "direction": direction, "ltp": round(ltp, 2), "move_pct": round(move, 2), "volx": round(volx, 1), "buy_share": round(share, 2),
                "vol_window": int(s.vol), "base_window": int(base_window), "day_move_pct": round((ltp / s.open - 1.0) * 100.0, 2)}


class EventLog:
    """Appends events to data/tick_events/<day>.csv (flushed on every event: there are few of them)."""

    def __init__(self, root: Path, day: str) -> None:
        self.path = root / "data" / "tick_events" / f"{day}.csv"
        self._lock = threading.Lock()
        self.count = 0

    def write(self, ev: Mapping[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.exists()
            with self.path.open("a", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow(ev)
            self.count += 1


_CACHE: dict[str, Any] = {"path": None, "mtime": 0.0, "rows": []}


def _events(root: Path, day: str) -> list[dict[str, str]]:
    path = root / "data" / "tick_events" / f"{day}.csv"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _CACHE["path"] != str(path) or _CACHE["mtime"] != mtime:
        try:
            with path.open(encoding="utf-8", newline="") as h:
                _CACHE.update(path=str(path), mtime=mtime, rows=list(csv.DictReader(h)))
        except OSError:
            return []
    return _CACHE["rows"]


def event_tags(symbol: str, direction: str, now: datetime, root: Path = ROOT, lookback_min: int = 15) -> dict[str, Any]:
    """Shadow tags for a candidate from today's events. Empty when the detector has not fired for this stock (td_fired = 0)."""
    try:
        mine = [e for e in _events(root, now.date().isoformat()) if e.get("symbol") == symbol]
        t_now = now.hour * 3600 + now.minute * 60 + now.second
        recent = [e for e in mine if 0 <= t_now - seconds(e["time"]) <= lookback_min * 60]
        out: dict[str, Any] = {"td_fired": int(bool(recent)), "td_n_today": len(mine)}
        if recent:
            last = recent[-1]
            out.update({"td_aligned": int(last["direction"] == str(direction).upper()), "td_ago_min": round((t_now - seconds(last["time"])) / 60.0, 1),
                        "td_volx": float(last["volx"]), "td_move_pct": float(last["move_pct"]), "td_buy_share": float(last["buy_share"])})
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}


def replay(day: str, symbols: Iterable[str] | None = None, root: Path = ROOT) -> list[dict[str, Any]]:
    """Run the detector over a recorded day (data/ticks/<day>/*.csv.gz) and return the events in time order."""
    folder = root / "data" / "ticks" / day
    want = {s.upper() for s in symbols} if symbols else None
    events: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.csv.gz")):
        sym = path.name[: -len(".csv.gz")]
        if want and sym not in want:
            continue
        det = TickDetector()
        try:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as h:
                for r in csv.DictReader(h):
                    try:
                        ev = det.update(sym, r["ts"], float(r["ltp"]), float(r["tq"] or 0), r["side"])
                    except (KeyError, ValueError):
                        continue
                    if ev:
                        events.append(ev)
        except (OSError, EOFError):
            continue                                       # a truncated gzip still yields what was read
    events.sort(key=lambda e: e["time"])
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", required=True, help="day to replay, e.g. 2026-10-22")
    ap.add_argument("--symbols", default="")
    a = ap.parse_args()
    ev = replay(a.replay, [s for s in a.symbols.split(",") if s.strip()] or None)
    for e in ev:
        print(f'{e["time"]}  {e["symbol"]:12} {e["direction"]:8} move {e["move_pct"]:+.2f}%  vol x{e["volx"]:<5} buy {e["buy_share"]:.2f}  day {e["day_move_pct"]:+.2f}%  ltp {e["ltp"]}')
    print(len(ev), "events,", len({e["symbol"] for e in ev}), "stocks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
