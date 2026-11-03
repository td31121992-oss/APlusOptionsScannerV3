"""Delta-flip detector: cumulative buy-minus-sell volume per stock and the moments it changes sign (SHADOW ONLY: events, tags and a review; nothing trades on it).

The idea (a channel's "Delta Flip" claim, 25 Oct 2026): follow the running difference between volume traded at the ask and at the bid ("delta"); when it turns from net selling to net buying (or the
reverse), the aggressive side has changed. We cannot see iceberg orders (the feed gives five depth levels, nothing order by order), so this uses what we have: every tick the recorder labels buyer- or
seller-initiated with the tick rule (price up / at the ask = B, down / at the bid = S) and the quantity traded since the previous packet.

    window delta    the last 15 minutes of signed volume (B positive, S negative) and their imbalance = delta / volume traded in the window, -1 .. +1
    state           +1 when the imbalance is at or above FLIP_IMB (0.15), -1 at or below -0.15, otherwise unchanged
    flip            the state turns from -1 to +1 (a BULL flip) or +1 to -1 (a BEAR flip), judged once a minute, when the window volume is at least HALF the stock's usual 15-minute pace today

    tags (dl_)      dl_imb15_dir  imbalance in the trade's direction (+ = buyers for a call, sellers for a put)      dl_day_imb_dir  the same over the whole day
                    dl_flip_dir   1 / -1 when the latest flip within 30 minutes agrees / disagrees with the trade, 0 when none      dl_flip_age_min   minutes since it
    data/delta_flips/<day>.csv    every flip as it happens (time, symbol, direction, imbalance, window delta and volume, price)
    data/ticks/delta_live.json    the live per-stock numbers, written every 20 s by the tick recorder

    python delta_flow.py replay YYYY-MM-DD     rebuild the day's flips from the recorded ticks (needs tick files that have the side and tq columns) and review them
    python delta_flow.py review [YYYY-MM-DD]   what the stocks did after each flip, against the market (5 / 15 / 30 / 60 minutes), live log or replay
"""

from __future__ import annotations

import csv
import json
import sys
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WINDOW_MIN = 15
FLIP_IMB = 0.15
MIN_REL_VOL = 0.5
OPEN_S = 9 * 3600 + 15 * 60
WRITE_EVERY_S = 20.0
FLIP_FRESH_MIN = 30
LIVE_PATH = ("data", "ticks", "delta_live.json")
FIELDS = ["date", "time", "symbol", "direction", "imbalance", "delta15", "vol15", "price"]


def _secs(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


class _S:
    __slots__ = ("cum", "vol", "minute", "hist", "state", "ltp", "flip", "imb")

    def __init__(self) -> None:
        self.cum = self.vol = 0.0
        self.minute = -1
        self.hist: deque[tuple[int, float, float]] = deque()      # (minute, cumulative delta, cumulative volume) at the END of each completed minute
        self.state = 0
        self.ltp = 0.0
        self.flip: dict[str, Any] | None = None
        self.imb = 0.0


class DeltaTracker:
    def __init__(self) -> None:
        self.state: dict[str, _S] = {}
        self._written = -1e9

    def update(self, sym: str, t_s: float, ltp: float, qty: float, side: str) -> dict[str, Any] | None:
        """One tick: price, quantity traded since the previous packet and the tick-rule side ('B' / 'S' / ''). Returns a flip event when this tick's minute boundary produced one."""
        if t_s < OPEN_S or ltp <= 0:
            return None
        s = self.state.get(sym)
        if s is None:
            s = self.state[sym] = _S()
        m = int(t_s // 60)
        ev = None
        if s.minute >= 0 and m > s.minute:
            for k in range(s.minute, min(m, s.minute + 30)):          # close every minute that just ended (a quiet minute repeats the totals)
                s.hist.append((k, s.cum, s.vol))
            while s.hist and s.hist[0][0] < m - WINDOW_MIN - 2:
                s.hist.popleft()
            ev = self._judge(sym, s, m, t_s)
        s.minute = m
        s.ltp = ltp
        if qty > 0 and side in ("B", "S"):
            s.cum += qty if side == "B" else -qty
        if qty > 0:
            s.vol += qty
        return ev

    def _judge(self, sym: str, s: _S, m: int, t_s: float) -> dict[str, Any] | None:
        old = next((h for h in s.hist if h[0] >= m - WINDOW_MIN - 1), None)
        if old is None:
            return None
        d, v = s.cum - old[1], s.vol - old[2]
        elapsed = max(1.0, (m - (OPEN_S // 60)))
        pace15 = s.vol / elapsed * WINDOW_MIN
        if v <= 0 or v < MIN_REL_VOL * pace15:
            return None
        imb = d / v
        s.imb = imb
        new = 1 if imb >= FLIP_IMB else -1 if imb <= -FLIP_IMB else 0
        if new == 0 or new == s.state:
            return None
        prev, s.state = s.state, new
        if prev == 0:
            return None                                                # the first non-neutral reading is a start, not a flip
        ev = {"time": f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}", "symbol": sym, "direction": new, "imbalance": round(imb, 3), "delta15": round(d), "vol15": round(v),
              "price": round(s.ltp, 2), "t": t_s}
        s.flip = ev
        return ev

    def snapshot(self, t_s: float) -> dict[str, Any]:
        out = {}
        for sym, s in self.state.items():
            out[sym] = {"imb": round(s.imb, 3), "day_imb": round(s.cum / s.vol, 3) if s.vol > 0 else 0.0, "state": s.state,
                        "flip": None if s.flip is None else {k: s.flip[k] for k in ("time", "direction", "imbalance", "price", "t")}}
        return out

    def maybe_write(self, root: Path, day: str, t_s: float, wall: float, events: list[dict[str, Any]]) -> bool:
        """Append new flips to the day's log, and (every WRITE_EVERY_S) rewrite the live file. Returns True when the live file was written."""
        if events:
            p = root / "data" / "delta_flips" / f"{day}.csv"
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                fresh = not p.exists()
                with p.open("a", encoding="utf-8", newline="") as h:
                    w = csv.DictWriter(h, fieldnames=FIELDS)
                    if fresh:
                        w.writeheader()
                    w.writerows([{"date": day, "time": e["time"], "symbol": e["symbol"], "direction": e["direction"], "imbalance": e["imbalance"], "delta15": e["delta15"], "vol15": e["vol15"],
                                  "price": e["price"]} for e in events])
            except OSError:
                pass
        if wall - self._written < WRITE_EVERY_S:
            return False
        self._written = wall
        out = {"day": day, "updated": f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}", "t": t_s, "stocks": self.snapshot(t_s)}
        p = root.joinpath(*LIVE_PATH)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(out), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            return False
        return True


_CACHE: dict[str, Any] = {"mtime": None, "data": None}


def load(root: Path, day: str) -> dict[str, Any] | None:
    path = root.joinpath(*LIVE_PATH)
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


def tags(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    try:
        d = load(root, now.date().isoformat())
        if not d:
            return {}
        s = d["stocks"].get(symbol)
        if not s:
            return {}
        sign = 1 if str(direction).upper() == "BULLISH" else -1
        out: dict[str, Any] = {"dl_imb15_dir": round(sign * s["imb"], 3), "dl_day_imb_dir": round(sign * s["day_imb"], 3), "dl_flip_dir": 0}
        f = s.get("flip")
        if f:
            age = (now.hour * 3600 + now.minute * 60 + now.second - f["t"]) / 60.0
            if 0 <= age <= FLIP_FRESH_MIN:
                out["dl_flip_dir"] = 1 if f["direction"] == sign else -1
                out["dl_flip_age_min"] = round(age, 1)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


# --- replay and review -----------------------------------------------------------------------------------------------------------------------------------------------------------
def replay_day(root: Path, day: str) -> list[dict[str, Any]]:
    """Every stock's flips for a recorded day, rebuilt from its tick file (columns ts, ltp, tq, side)."""
    import tick_gz

    events: list[dict[str, Any]] = []
    for path in sorted((root / "data" / "ticks" / day).glob("*.csv.gz")):
        text, _m, _b = tick_gz.read_text(path)
        lines = text.splitlines()
        if len(lines) < 2:
            continue
        col = {n: i for i, n in enumerate(lines[0].split(","))}
        if not all(k in col for k in ("ts", "sym", "ltp", "tq", "side")):
            continue
        tr = DeltaTracker()
        i_ts, i_sym, i_ltp, i_tq, i_side = (col[k] for k in ("ts", "sym", "ltp", "tq", "side"))
        for ln in lines[1:]:
            p = ln.split(",")
            if len(p) <= max(i_tq, i_side):
                continue
            try:
                ev = tr.update(p[i_sym], _secs(p[i_ts]), float(p[i_ltp]), float(p[i_tq] or 0), p[i_side])
            except ValueError:
                continue
            if ev:
                events.append(ev)
    events.sort(key=lambda e: e["t"])
    return events


def review(root: Path = ROOT, day: str | None = None, force_replay: bool = False) -> Path | None:
    import rs_replay

    day = day or date.today().isoformat()
    log = root / "data" / "delta_flips" / f"{day}.csv"
    if log.exists() and not force_replay:
        with log.open(encoding="utf-8", newline="") as h:
            flips = [{"time": r["time"], "symbol": r["symbol"], "direction": int(r["direction"])} for r in csv.DictReader(h)]
        source = "live flip log"
    else:
        flips = replay_day(root, day)
        source = "replayed from ticks"
    if not flips:
        return None
    samples = rs_replay.load_samples(root, day)
    if not samples:
        return None
    series = rs_replay.series_by_symbol(samples)
    events = [{"time": f["time"], "symbol": f["symbol"], "kind": "LEADER_BULL_FLIP" if f["direction"] > 0 else "LAGGARD_BEAR_FLIP"} for f in flips]
    rows = rs_replay.forward_moves(events, series, day)
    table = rs_replay._group(rows, lambda r: r["kind"])
    folder = root / "data" / "delta_flips"
    folder.mkdir(parents=True, exist_ok=True)
    L = [f"# Delta flips, {day} ({source})", "", f"{len(flips)} flips. Excess = the stock's move in the flip's direction (bull flip = up, bear flip = down) minus the median stock's over the same minutes, stock level.", ""]
    L += rs_replay._fmt_quality(table)
    out = folder / f"review_{day}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


def run(day: str, root: Path = ROOT) -> None:
    review(root, day)


def main() -> int:
    a = sys.argv[1:]
    if a and a[0] == "replay":
        out = review(ROOT, a[1], force_replay=True)
    else:
        out = review(ROOT, a[0] if a else None)
    print(out or "nothing to review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
