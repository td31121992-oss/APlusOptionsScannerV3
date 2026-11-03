"""Candle story: what every 5-minute candle of every F&O stock says, and what the last few candles say together (SHADOW / DISPLAY ONLY: labels, a page, tags and a review; nothing trades on it).

From every tick (price, traded quantity, buyer / seller side by the tick rule) each stock's 5-minute candles are built with their volume and buyer-minus-seller volume. When a candle closes it gets a
plain meaning from its shape, its volume against the last few candles, its buyer / seller balance and where it sits (previous day's high / low, the first-hour range, the day's high / low, VWAP):

  ONE CANDLE      FAILED_BREAK_UP / _DOWN   the candle pierced a level (PDH / first-hour high, or the low side) but closed back inside it with a long wick: the move was refused
                  BREAK_UP / BREAK_DOWN     a candle with a real body closed beyond the level for the first time
                  BURST_UP / BURST_DOWN     range 2.5x the recent average on 2x volume, closing at its extreme
                  REJECTION_HIGH / _LOW     a wick of half the candle or more against the close (sellers refused the high / buyers defended the low)
                  ABSORPTION_HIGH / _LOW    heavy volume near the day's high / low but the candle goes nowhere (the push was absorbed)
                  MOMENTUM_UP / _DOWN       a strong body closing in the top / bottom fifth on normal or better volume
                  INDECISION, DRIFT_UP / _DOWN, FLAT
  SEQUENCE        PULLBACK_UP_RESUMES / _DOWN_RESUMES   after a run of 0.8 %+, two or three small counter candles on lighter volume, then the move resumes (the "wait for retest" entry)
                  PULLBACK_UP / _DOWN       the same pullback is under way (not yet resumed)
                  BASE_BREAK_UP / _DOWN     six candles inside a 1 % box, then a candle closes out of it on 1.3x volume
                  BREAKOUT_RETEST_UP / _DOWN   a level broke in the last six candles, price came back to it and held
                  EXHAUSTION_UP / _DOWN     after a run of 1.5 %+ the move meets a rejection or a failed break at the extreme (a reversal warning)
                  COILING                   six quiet candles in under 0.8 % with falling volume
    The sequence label wins the "story" when there is one; otherwise the story is the last candle's label.

    data/ticks/candle_story_live.json    every stock's last 12 candles with their labels and the current story (written every 10 s by the tick recorder); the /candle-story page reads it
    data/candle_story/<day>.csv          each notable label (not INDECISION / DRIFT / FLAT) as it forms: time, stock, kind (candle or story), label, price
    tags (cs_)    cs_last  label of the last closed candle    cs_story  the current story    cs_with  +1 the story supports the trade's direction, -1 opposes it, 0 neutral
                  cs_vol_x  the last candle's volume against the recent average    cs_delta_dir  the last candle's buyer-minus-seller share in the trade's direction    cs_last3  the last three labels

    python candle_story.py replay YYYY-MM-DD    rebuild a recorded day's labels from its tick files and review them against what the stocks did next
    python candle_story.py review [YYYY-MM-DD]  the same from the live label log
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
OPEN_S = 9 * 3600 + 15 * 60
BAR_S = 300
IB_END_S = OPEN_S + 3600
KEEP = 12
LOOK = 6
WRITE_EVERY_S = 10.0
LIVE_PATH = ("data", "ticks", "candle_story_live.json")
FIELDS = ["date", "time", "symbol", "kind", "label", "price", "vol_x", "delta"]
QUIET = {"INDECISION", "DRIFT_UP", "DRIFT_DOWN", "FLAT", "NONE", "COILING"}
BULL = {"BREAK_UP", "BURST_UP", "REJECTION_LOW", "ABSORPTION_LOW", "MOMENTUM_UP", "FAILED_BREAK_DOWN", "PULLBACK_UP_RESUMES", "BASE_BREAK_UP", "BREAKOUT_RETEST_UP", "EXHAUSTION_DOWN", "PULLBACK_UP"}
BEAR = {"BREAK_DOWN", "BURST_DOWN", "REJECTION_HIGH", "ABSORPTION_HIGH", "MOMENTUM_DOWN", "FAILED_BREAK_UP", "PULLBACK_DOWN_RESUMES", "BASE_BREAK_DOWN", "BREAKOUT_RETEST_DOWN", "EXHAUSTION_UP", "PULLBACK_DOWN"}


def direction_of(label: str) -> int:
    return 1 if label in BULL else -1 if label in BEAR else 0


class Candle:
    __slots__ = ("t0", "o", "h", "l", "c", "v", "buy", "sell", "label", "story")

    def __init__(self, t0: float, price: float) -> None:
        self.t0, self.o, self.h, self.l, self.c = t0, price, price, price, price
        self.v = self.buy = self.sell = 0.0
        self.label = self.story = ""

    def add(self, price: float, qty: float, side: str) -> None:
        self.h, self.l, self.c = max(self.h, price), min(self.l, price), price
        if qty > 0:
            self.v += qty
            if side == "B":
                self.buy += qty
            elif side == "S":
                self.sell += qty


def _avg(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def label_candle(c: Candle, hist: Sequence[Candle], ctx: dict[str, Any]) -> tuple[str, float, float]:
    """(label, volume multiple, buyer-minus-seller share) for a closed candle given up to LOOK earlier candles and the context levels."""
    rng = c.h - c.l
    if rng <= 0 or c.o <= 0:
        return "FLAT", 1.0, 0.0
    body = abs(c.c - c.o) / rng
    up_w, lo_w = (c.h - max(c.o, c.c)) / rng, (min(c.o, c.c) - c.l) / rng
    pos = (c.c - c.l) / rng
    prev = list(hist)[-LOOK:]
    avg_v, avg_r = _avg([x.v for x in prev]), _avg([x.h - x.l for x in prev])
    vol_x = c.v / avg_v if avg_v > 0 else 1.0
    rng_x = rng / avg_r if avg_r > 0 else 1.0
    delta = (c.buy - c.sell) / c.v if c.v > 0 else 0.0
    prev_close = hist[-1].c if hist else c.o
    up_levels = [x for x in (ctx.get("pdh"), ctx.get("ib_hi"), ctx.get("day_hi")) if x]
    dn_levels = [x for x in (ctx.get("pdl"), ctx.get("ib_lo"), ctx.get("day_lo")) if x]
    pierced_up = next((lv for lv in up_levels if c.h > lv * 1.0005 and c.c < lv and prev_close < lv), None)
    pierced_dn = next((lv for lv in dn_levels if c.l < lv * 0.9995 and c.c > lv and prev_close > lv), None)
    broke_up = next((lv for lv in up_levels if prev_close <= lv < c.c and body >= 0.4), None)
    broke_dn = next((lv for lv in dn_levels if prev_close >= lv > c.c and body >= 0.4), None)
    near_hi = bool(ctx.get("day_hi")) and c.c >= ctx["day_hi"] * 0.998
    near_lo = bool(ctx.get("day_lo")) and c.c <= ctx["day_lo"] * 1.002
    if pierced_up and up_w >= 0.4:
        lab = "FAILED_BREAK_UP"
    elif pierced_dn and lo_w >= 0.4:
        lab = "FAILED_BREAK_DOWN"
    elif broke_up:
        lab = "BREAK_UP"
    elif broke_dn:
        lab = "BREAK_DOWN"
    elif rng_x >= 2.5 and vol_x >= 2.0 and body >= 0.6 and pos >= 0.8 and c.c > c.o:
        lab = "BURST_UP"
    elif rng_x >= 2.5 and vol_x >= 2.0 and body >= 0.6 and pos <= 0.2 and c.c < c.o:
        lab = "BURST_DOWN"
    elif up_w >= 0.5 and pos <= 0.45 and rng_x >= 0.8:
        lab = "REJECTION_HIGH"
    elif lo_w >= 0.5 and pos >= 0.55 and rng_x >= 0.8:
        lab = "REJECTION_LOW"
    elif vol_x >= 1.5 and body <= 0.35 and near_hi:
        lab = "ABSORPTION_HIGH"
    elif vol_x >= 1.5 and body <= 0.35 and near_lo:
        lab = "ABSORPTION_LOW"
    elif body >= 0.6 and pos >= 0.8 and c.c > c.o and vol_x >= 1.0:
        lab = "MOMENTUM_UP"
    elif body >= 0.6 and pos <= 0.2 and c.c < c.o and vol_x >= 1.0:
        lab = "MOMENTUM_DOWN"
    elif body <= 0.25:
        lab = "INDECISION"
    else:
        lab = "DRIFT_UP" if c.c > c.o else "DRIFT_DOWN"
    return lab, round(vol_x, 2), round(delta, 3)


def sequence_story(candles: Sequence[Candle], labels: Sequence[str], vwap: float | None) -> str:
    """The multi-candle story of the last candles, '' when none applies. `candles` includes the latest closed candle; `labels` are their one-candle labels."""
    n = len(candles)
    if n < 7:
        return ""
    c = candles[-1]
    last = candles[-1].c
    base_c = candles[-13].c if n >= 13 else candles[0].c
    trend = (last / base_c - 1.0) * 100.0 if base_c > 0 else 0.0
    avg_v = _avg([x.v for x in candles[-9:-3]])
    recent = candles[-4:]
    # a break in the last six candles that price has come back to and held
    for k in range(2, 7):
        lab = labels[-k]
        if lab in ("BREAK_UP", "BREAK_DOWN") and n > k:
            lvl = candles[-k - 1].h if lab == "BREAK_UP" else candles[-k - 1].l
            if lab == "BREAK_UP" and c.l <= lvl * 1.002 and c.c > lvl and c.l >= lvl * 0.995:
                return "BREAKOUT_RETEST_UP"
            if lab == "BREAK_DOWN" and c.h >= lvl * 0.998 and c.c < lvl and c.h <= lvl * 1.005:
                return "BREAKOUT_RETEST_DOWN"
    # exhaustion: a long run meets a refusal at the extreme
    if trend >= 1.5 and labels[-1] in ("REJECTION_HIGH", "FAILED_BREAK_UP", "ABSORPTION_HIGH"):
        return "EXHAUSTION_UP"
    if trend <= -1.5 and labels[-1] in ("REJECTION_LOW", "FAILED_BREAK_DOWN", "ABSORPTION_LOW"):
        return "EXHAUSTION_DOWN"
    # base break: six candles in a 1 % box, then a candle closes out of it on volume
    box = candles[-7:-1]
    hi, lo = max(x.h for x in box), min(x.l for x in box)
    mid = (hi + lo) / 2.0
    box_avg_v = _avg([x.v for x in box])
    if mid > 0 and (hi - lo) / mid * 100.0 <= 1.0 and box_avg_v > 0 and c.v >= 1.3 * box_avg_v:
        if c.c > hi:
            return "BASE_BREAK_UP"
        if c.c < lo:
            return "BASE_BREAK_DOWN"
    # pullbacks after a run (needs nine candles: the run, the pullback, and light-volume candles to compare with)
    if n >= 9:
        for up in (True, False):
            sign = 1 if up else -1
            if sign * trend < 0.8:
                continue
            is_ctr = lambda x: ((x.c < x.o) if up else (x.c > x.o)) or abs(x.c - x.o) <= 0.25 * max(x.h - x.l, 1e-9)
            avg_run_v = _avg([x.v for x in candles[-9:-3]])
            light = lambda xs: bool(xs) and avg_run_v > 0 and _avg([x.v for x in xs]) < avg_run_v
            vwap_ok = vwap is None or (last >= vwap if up else last <= vwap)
            if not vwap_ok:
                continue
            pre_ctr = [x for x in candles[-4:-1] if is_ctr(x)]
            moving = (c.c > c.o and labels[-1] in ("MOMENTUM_UP", "DRIFT_UP", "BREAK_UP", "REJECTION_LOW")) if up else (c.c < c.o and labels[-1] in ("MOMENTUM_DOWN", "DRIFT_DOWN", "BREAK_DOWN", "REJECTION_HIGH"))
            if moving and 2 <= len(pre_ctr) <= 3 and light(pre_ctr):
                return "PULLBACK_UP_RESUMES" if up else "PULLBACK_DOWN_RESUMES"
            last3 = [x for x in candles[-3:] if is_ctr(x)]
            if is_ctr(c) and len(last3) >= 2 and light(last3):
                return "PULLBACK_UP" if up else "PULLBACK_DOWN"
    last6 = candles[-6:]
    h6, l6 = max(x.h for x in last6), min(x.l for x in last6)
    if h6 > 0 and (h6 - l6) / ((h6 + l6) / 2.0) * 100.0 <= 0.8 and _avg([x.v for x in last6[3:]]) < _avg([x.v for x in last6[:3]]):
        return "COILING"
    return ""


class _St:
    __slots__ = ("cur", "done", "labels", "stories", "pv", "vv", "hi", "lo", "ib_hi", "ib_lo", "pdh", "pdl", "last_logged")

    def __init__(self) -> None:
        self.cur: Candle | None = None
        self.done: list[Candle] = []
        self.labels: list[str] = []
        self.stories: list[str] = []
        self.pv = self.vv = 0.0
        self.hi = self.lo = self.ib_hi = self.ib_lo = 0.0
        self.pdh = self.pdl = 0.0
        self.last_logged: dict[str, float] = {}


class StoryTracker:
    def __init__(self, levels: dict[str, tuple[float, float]] | None = None) -> None:
        self.state: dict[str, _St] = {}
        self.levels = levels or {}
        self._written = -1e9

    def update(self, sym: str, t_s: float, ltp: float, qty: float, side: str) -> list[dict[str, Any]]:
        """One tick. Returns the notable labels formed by the candle this tick closed (usually none)."""
        if t_s < OPEN_S or ltp <= 0:
            return []
        s = self.state.get(sym)
        if s is None:
            s = self.state[sym] = _St()
            s.pdh, s.pdl = self.levels.get(sym, (0.0, 0.0))
        t0 = OPEN_S + int((t_s - OPEN_S) // BAR_S) * BAR_S
        out: list[dict[str, Any]] = []
        if s.cur is not None and t0 > s.cur.t0:
            out = self._close(sym, s, t_s)
            s.cur = None
        if s.cur is None:
            s.cur = Candle(t0, ltp)
        s.cur.add(ltp, qty, side)
        if qty > 0:
            s.pv += ltp * qty
            s.vv += qty
        s.hi, s.lo = (ltp, ltp) if not s.hi else (max(s.hi, ltp), min(s.lo, ltp))
        if t_s < IB_END_S:
            s.ib_hi, s.ib_lo = (ltp, ltp) if not s.ib_hi else (max(s.ib_hi, ltp), min(s.ib_lo, ltp))
        return out

    def _close(self, sym: str, s: _St, t_s: float) -> list[dict[str, Any]]:
        c = s.cur
        assert c is not None
        ctx = {"pdh": s.pdh, "pdl": s.pdl, "day_hi": max((x.h for x in s.done), default=0.0) or None, "day_lo": min((x.l for x in s.done), default=0.0) or None,
               "ib_hi": s.ib_hi if c.t0 >= IB_END_S else None, "ib_lo": s.ib_lo if c.t0 >= IB_END_S else None}
        lab, vol_x, delta = label_candle(c, s.done, ctx)
        c.label = lab
        s.done.append(c)
        s.labels.append(lab)
        vwap = s.pv / s.vv if s.vv > 0 else None
        story = sequence_story(s.done, s.labels, vwap)
        c.story = story
        s.stories.append(story)
        out = []
        end_s = c.t0 + BAR_S
        stamp = f"{int(end_s // 3600):02d}:{int(end_s % 3600 // 60):02d}:00"
        for kind, name in (("candle", lab), ("story", story)):
            if name and name not in QUIET and end_s - s.last_logged.get(kind + name, -1e9) >= 900:
                s.last_logged[kind + name] = end_s
                out.append({"time": stamp, "symbol": sym, "kind": kind, "label": name, "price": round(c.c, 2), "vol_x": vol_x, "delta": delta, "t": end_s})
        return out

    def story_of(self, s: _St) -> str:
        return (s.stories[-1] if s.stories and s.stories[-1] else (s.labels[-1] if s.labels else ""))

    def snapshot(self) -> dict[str, Any]:
        out = {}
        for sym, s in self.state.items():
            if not s.done:
                continue
            out[sym] = {"story": self.story_of(s), "last": s.labels[-1], "ltp": round(s.cur.c if s.cur else s.done[-1].c, 2), "vwap": round(s.pv / s.vv, 2) if s.vv > 0 else None,
                        "pdh": s.pdh or None, "pdl": s.pdl or None, "ib_hi": round(s.ib_hi, 2) if s.ib_hi else None, "ib_lo": round(s.ib_lo, 2) if s.ib_lo else None,
                        "candles": [{"t": f"{int((c.t0) // 3600):02d}:{int(c.t0 % 3600 // 60):02d}", "o": round(c.o, 2), "h": round(c.h, 2), "l": round(c.l, 2), "c": round(c.c, 2), "v": int(c.v),
                                     "d": round((c.buy - c.sell) / c.v, 2) if c.v else 0.0, "lab": c.label, "story": c.story} for c in s.done[-KEEP:]]}
        return out

    def maybe_write(self, root: Path, day: str, t_s: float, wall: float, events: list[dict[str, Any]]) -> bool:
        if events:
            p = root / "data" / "candle_story" / f"{day}.csv"
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                fresh = not p.exists()
                with p.open("a", encoding="utf-8", newline="") as h:
                    w = csv.DictWriter(h, fieldnames=FIELDS)
                    if fresh:
                        w.writeheader()
                    w.writerows([{"date": day, **{k: e[k] for k in FIELDS[1:]}} for e in events])
            except OSError:
                pass
        if wall - self._written < WRITE_EVERY_S:
            return False
        self._written = wall
        out = {"day": day, "updated": f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}", "t": t_s, "stocks": self.snapshot()}
        p = root.joinpath(*LIVE_PATH)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(out), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            return False
        return True


def load_levels(root: Path) -> dict[str, tuple[float, float]]:
    """Previous day's high / low per stock from data/reports/daily_indicators.json."""
    try:
        d = json.loads(root.joinpath("data", "reports", "daily_indicators.json").read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        return {}
    return {s: (float(v.get("pdh") or 0), float(v.get("pdl") or 0)) for s, v in d.items()}


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
        s = d["stocks"].get(symbol) if d else None
        if not s or not s["candles"]:
            return {}
        sign = 1 if str(direction).upper() == "BULLISH" else -1
        last = s["candles"][-1]
        story = s["story"]
        prev_v = [c["v"] for c in s["candles"][-1 - LOOK:-1]]
        vol_x = round(last["v"] / (sum(prev_v) / len(prev_v)), 2) if prev_v and sum(prev_v) > 0 else None
        return {"cs_last": s["last"], "cs_story": story, "cs_with": sign * direction_of(story), "cs_vol_x": vol_x, "cs_delta_dir": round(sign * last["d"], 2),
                "cs_last3": "|".join(c["lab"] for c in s["candles"][-3:])}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


def payload(root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    d = load(root, (today or date.today()).isoformat())
    if not d:
        return {"ok": False, "error": "no candle stories yet today (the tick recorder runs 09:05-15:32; the first candle closes at 09:20)"}
    return {"ok": True, "updated": d["updated"], "stocks": d["stocks"], "bull": sorted(BULL), "bear": sorted(BEAR)}


# --- replay and review -----------------------------------------------------------------------------------------------------------------------------------------------------------
def _secs(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def replay_day(root: Path, day: str) -> list[dict[str, Any]]:
    import tick_gz

    levels = load_levels(root)
    events: list[dict[str, Any]] = []
    for path in sorted((root / "data" / "ticks" / day).glob("*.csv.gz")):
        text, _m, _b = tick_gz.read_text(path)
        lines = text.splitlines()
        if len(lines) < 2:
            continue
        col = {n: i for i, n in enumerate(lines[0].split(","))}
        if not all(k in col for k in ("ts", "sym", "ltp", "tq", "side")):
            continue
        tr = StoryTracker(levels)
        i_ts, i_sym, i_ltp, i_tq, i_side = (col[k] for k in ("ts", "sym", "ltp", "tq", "side"))
        for ln in lines[1:]:
            p = ln.split(",")
            if len(p) <= max(i_tq, i_side):
                continue
            try:
                events += tr.update(p[i_sym], _secs(p[i_ts]), float(p[i_ltp]), float(p[i_tq] or 0), p[i_side])
            except ValueError:
                continue
    events.sort(key=lambda e: e["t"])
    return events


def review(root: Path = ROOT, day: str | None = None, force_replay: bool = False) -> Path | None:
    import rs_replay

    day = day or date.today().isoformat()
    log = root / "data" / "candle_story" / f"{day}.csv"
    if log.exists() and not force_replay:
        with log.open(encoding="utf-8", newline="") as h:
            evs = [{"time": r["time"], "symbol": r["symbol"], "kind": r["kind"], "label": r["label"]} for r in csv.DictReader(h)]
        source = "live label log"
    else:
        evs = replay_day(root, day)
        source = "replayed from ticks"
    evs = [e for e in evs if direction_of(e["label"]) != 0]
    if not evs:
        return None
    samples = rs_replay.load_samples(root, day)
    if not samples:
        return None
    series = rs_replay.series_by_symbol(samples)
    events = [{"time": e["time"], "symbol": e["symbol"], "kind": ("LEADER_" if direction_of(e["label"]) > 0 else "LAGGARD_") + e["kind"].upper() + "_" + e["label"]} for e in evs]
    rows = rs_replay.forward_moves(events, series, day)
    table = rs_replay._group(rows, lambda r: r["kind"])
    folder = root / "data" / "candle_story"
    folder.mkdir(parents=True, exist_ok=True)
    L = [f"# Candle stories, {day} ({source})", "", f"{len(evs)} directional labels. Excess = the stock's move in the label's direction (bullish up, bearish down) minus the median stock's over the same minutes, stock level.", ""]
    L += rs_replay._fmt_quality(table)
    out = folder / f"review_{day}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


def run(day: str, root: Path = ROOT) -> None:
    review(root, day)


def main() -> int:
    a = sys.argv[1:]
    out = review(ROOT, a[1], force_replay=True) if a and a[0] == "replay" else review(ROOT, a[0] if a else None)
    print(out or "nothing to review")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
