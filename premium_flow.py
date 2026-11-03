"""Intraday option-premium flow per stock (SHADOW tags: recorded on the candidate / trade, never used to allow or block anything).

The Premium Tracker page shows each stock's option premium traded and "x avg" (today's total over its own average), but only as an end-of-day figure, which cannot be used at entry time.
This builds the entry-time version from the Upstox chain collector's 5-minute captures (nearest expiry, +-8 strikes of the money):

    premium traded in a capture = (volume now - volume at the previous capture) x last price, per leg, summed over calls and puts, in Rs crore
    data/options_intelligence_upstox/<day>/premium_flow.csv     captured_at, symbol, ce_cr, pe_cr    (the increment in each capture; written by the collector)

Tags at entry (px_ prefix; blank values when there is no data yet):

    px_cum_cr         premium traded so far today (calls + puts)
    px_days           earlier days of history for this stock (the baseline needs APLUS_PX_MIN_DAYS, default 3)
    px_x_avg          px_cum_cr over the average premium the stock had traded by the same time on earlier days
    px_last15_cr      premium traded in the last 15 minutes
    px_surge15_x      px_last15_cr over the stock's usual premium per 15 minutes at this time of day (its earlier-days average so far, spread evenly)
    px_dir_share      share of today's premium on OUR option type (calls for a BULLISH trade, puts for a BEARISH one), 0..1
    px_dir_share15    the same share over the last 15 minutes

A leg that only enters the +-8 strike window as the stock moves is not counted from its cumulative volume (its first sighting just starts the count), so a shifting window does not
create fake bursts. The pre-open capture (09:14) reports the previous day's volume, so it only sets the baseline. Rebuild a day from the raw captures with  python premium_flow.py YYYY-MM-DD.
"""

from __future__ import annotations

import csv
import gzip
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent
CR = 1e7
FOLDER = ("data", "options_intelligence_upstox")
FIELDS = ["captured_at", "symbol", "ce_cr", "pe_cr"]
OPEN_MIN = 9 * 60 + 15


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _min(stamp: str) -> int:
    """'2026-10-22T09:14:01+05:30' -> minute of day."""
    return int(stamp[11:13]) * 60 + int(stamp[14:16])


class Accumulator:
    """Turns successive chain captures (lists of leg rows) into per-stock premium increments."""

    def __init__(self) -> None:
        self.last: dict[tuple[str, str, float, str], float] = {}
        self.captures = 0

    def update(self, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        rows = list(rows)
        # The day's first capture counts the volume traded so far only when it is taken after the open. The collector's first capture is at 09:14, BEFORE the open, when the feed
        # still reports the PREVIOUS day's volume: that one only sets the baseline (counting it doubled every day's premium; found by comparing with NSE's end-of-day file).
        first = self.captures == 0 and bool(rows) and _min(str(rows[0].get("captured_at") or "")) > OPEN_MIN
        inc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        stamp = ""
        for r in rows:
            stamp = str(r.get("captured_at") or stamp)
            key = (str(r.get("symbol")), str(r.get("expiry")), _f(r.get("strike")), str(r.get("side")))
            vol, px = _f(r.get("volume")), _f(r.get("ltp"))
            prev = self.last.get(key)
            self.last[key] = vol
            delta = vol if (prev is None and first) else (vol - prev if prev is not None and vol >= prev else 0.0)
            if delta > 0 and px > 0:
                inc[key[0]][0 if key[3] == "CE" else 1] += delta * px
            else:
                inc.setdefault(key[0], [0.0, 0.0])
        self.captures += 1
        return [{"captured_at": stamp, "symbol": s, "ce_cr": round(v[0] / CR, 4), "pe_cr": round(v[1] / CR, 4)} for s, v in inc.items()]


def day_folder(root: Path, day: str) -> Path:
    return root.joinpath(*FOLDER, day)


def append(folder: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "premium_flow.csv"
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def replay(folder: Path, write: bool) -> Accumulator:
    """Stream a day's raw captures through a fresh accumulator (to rebuild premium_flow.csv, or to restore the collector's state after a restart)."""
    acc = Accumulator()
    src = folder / "option_chain_rows.csv.gz"
    out = folder / "premium_flow.csv"
    if write and out.exists():
        out.unlink()
    if not src.exists():
        return acc
    batch: list[dict[str, str]] = []
    stamp = None
    try:
        with gzip.open(src, "rt", encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                if r["captured_at"] != stamp and batch:
                    rows = acc.update(batch)
                    if write:
                        append(folder, rows)
                    batch = []
                stamp = r["captured_at"]
                batch.append(r)
    except (OSError, EOFError):
        pass                                               # a truncated file still yields the captures read so far
    if batch:
        rows = acc.update(batch)
        if write:
            append(folder, rows)
    return acc


_CACHE: dict[str, tuple[float, dict[str, list[tuple[int, float, float]]]]] = {}


def _load(root: Path, day: str) -> dict[str, list[tuple[int, float, float]]]:
    """symbol -> [(minute of day, ce_cr, pe_cr)] ascending, cached by file modification time."""
    path = day_folder(root, day) / "premium_flow.csv"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    hit = _CACHE.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    data: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    try:
        with path.open(encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                data[r["symbol"]].append((_min(r["captured_at"]), _f(r["ce_cr"]), _f(r["pe_cr"])))
    except (OSError, ValueError, KeyError):
        return {}
    for v in data.values():
        v.sort()
    _CACHE[str(path)] = (mtime, dict(data))
    return _CACHE[str(path)][1]


def _earlier_days(root: Path, day: str, n: int = 10) -> list[str]:
    base = root.joinpath(*FOLDER)
    try:
        days = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name < day and (p / "premium_flow.csv").exists())
    except OSError:
        return []
    return days[-n:]


def _cum(series: list[tuple[int, float, float]], upto: int) -> tuple[float, float]:
    return sum(c for m, c, _p in series if m <= upto), sum(p for m, _c, p in series if m <= upto)


def tags(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    """Shadow tags for a candidate from today's captures and the earlier days' (see the module docstring). {} when there is nothing for today."""
    try:
        minute = now.hour * 60 + now.minute
        today = _load(root, now.date().isoformat()).get(symbol)
        if not today:
            return {}
        ce, pe = _cum(today, minute)
        total = ce + pe
        c15, p15 = _cum([x for x in today if x[0] > minute - 15], minute)
        want_ce = str(direction).upper() == "BULLISH"
        out: dict[str, Any] = {"px_cum_cr": round(total, 2), "px_last15_cr": round(c15 + p15, 2),
                               "px_dir_share": round((ce if want_ce else pe) / total, 2) if total > 0 else "",
                               "px_dir_share15": round((c15 if want_ce else p15) / (c15 + p15), 2) if c15 + p15 > 0 else ""}
        past = []
        for d in _earlier_days(root, now.date().isoformat()):
            series = _load(root, d).get(symbol)
            if series:
                c, p = _cum(series, minute)
                if c + p > 0:
                    past.append(c + p)
        out["px_days"] = len(past)
        if len(past) >= int(os.getenv("APLUS_PX_MIN_DAYS", "3") or 3):
            base = st.mean(past)
            out["px_x_avg"] = round(total / base, 2)
            elapsed = max(15, minute - OPEN_MIN)
            per15 = base * 15.0 / elapsed
            out["px_surge15_x"] = round((c15 + p15) / per15, 2) if per15 > 0 else ""
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now().date().isoformat()
    folder = day_folder(ROOT, day)
    acc = replay(folder, write=True)
    print(day, "captures:", acc.captures, "->", folder / "premium_flow.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
