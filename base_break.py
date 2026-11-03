"""Base-break detector: a stock that HOLDS while the market moves against the trade, builds a tight base, then breaks it (SHADOW ONLY: events, tags and a review; nothing trades on it).

The example (ETERNAL, 23 Oct 2026): the market fell 2.5 % with 95 % of stocks down; ETERNAL stayed flat for an hour (2-2.6 % ahead of the market, a 303-306 base), then broke above 305 on a green
candle at 11:05 and ran to 316. The 305 call went from 5 to 10. Our scanner saw it six minutes after the break (option already 8) and held it back with its "too late" rules.

A BULL event (call) needs all of:
    market   the median stock is at least MARKET_MOVE (1 %) down since the open (return since 09:15 on 5-minute closes) and at most MAX_BREADTH (35 %) of stocks are up
    strength the stock is at least MIN_RS (1.5 %) ahead of the market since the open
    base     the last BASE_BARS (6 five-minute bars = 30 minutes) closes before this bar stayed within BASE_RANGE (1.2 %) of each other
    break    this bar closes more than BREAK_PCT (0.15 %) above the base high, and is up at least MOMENTUM_PCT (0.30 %) on the bar before
    time     between 10:00 and 14:00
A BEAR event (put) is the mirror: a green market (median up 1 %+), the stock weaker than it by 1.5 %+, a base, a break below it. Each stock and side fires at most once a day (the first break).

    evaluate(bars_by_symbol, minute)  -> list of events, from the 5-minute closes made out of the tick recorder's one-minute series (ml_shadow.MinuteBars) or from history; the back-test
                                         (base_break_backtest.py) runs the identical function on 87 days of 5-minute spot data.
    LiveDetector.update(...)          -> called by the tick recorder every 20 s: logs new events to data/base_breaks/<day>.csv, writes data/ticks/base_break_live.json
    tags(symbol, direction, now)      -> bb_ tags for a candidate: bb_fired (today), bb_age_min, bb_rs, bb_break_pct
"""

from __future__ import annotations

import csv
import json
import statistics as st
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
OPEN_MIN = 9 * 60 + 15
BAR_MIN = 5                                  # the series are 5-minute bar closes (index 0 = the 09:15 bar), the resolution of the stored history the rule is back-tested on
FIRST_MIN, LAST_MIN = 10 * 60, 14 * 60
MARKET_MOVE, MAX_BREADTH, MIN_RS = 1.0, 0.35, 1.5
BASE_BARS, BASE_RANGE = 6, 1.2                # 6 bars = a 30-minute base
BREAK_PCT, MOMENTUM_PCT, MOMENTUM_BARS = 0.15, 0.30, 1
MIN_STOCKS = 100
LIVE_PATH = ("data", "ticks", "base_break_live.json")
FIELDS = ["date", "time", "symbol", "side", "ret_open", "rs", "mkt", "breadth_up", "base_range_pct", "break_pct", "mom3_pct", "price"]


def check(closes: Sequence[float], side: int, mkt: float, breadth_up: float, gate: bool = True, base_range: float | None = BASE_RANGE) -> dict[str, Any] | None:
    """Evaluate the rule on one stock's closes (index 0 = 09:15, last = the bar just closed). `side` +1 = call (red market), -1 = put (green market). None when it does not hold.
    gate=False skips the market conditions (strength is still measured against the real market); base_range=None drops the tight-base requirement (the break is still of the 30-bar high / low). Both exist for the back-test variants."""
    n = len(closes)
    if n < BASE_BARS + 2 or closes[0] <= 0:
        return None
    minute = OPEN_MIN + BAR_MIN * (n - 1)
    if minute < FIRST_MIN or minute > LAST_MIN:
        return None
    if gate:
        if side > 0:
            if mkt > -MARKET_MOVE or breadth_up > MAX_BREADTH:
                return None
        elif mkt < MARKET_MOVE or breadth_up < 1.0 - MAX_BREADTH:
            return None
    ret_open = (closes[-1] / closes[0] - 1.0) * 100.0
    rs = side * (ret_open - mkt)
    if rs < MIN_RS:
        return None
    base = closes[-1 - BASE_BARS:-1]
    hi, lo = max(base), min(base)
    mid = (hi + lo) / 2.0
    if mid <= 0 or (base_range is not None and (hi - lo) / mid * 100.0 > base_range):
        return None
    last = closes[-1]
    brk = ((last / hi - 1.0) if side > 0 else (lo / last - 1.0)) * 100.0
    if brk < BREAK_PCT:
        return None
    mom = side * (last / closes[-1 - MOMENTUM_BARS] - 1.0) * 100.0
    if mom < MOMENTUM_PCT:
        return None
    return {"minute": minute, "side": side, "ret_open": round(ret_open, 3), "rs": round(rs, 3), "mkt": round(mkt, 3), "breadth_up": round(breadth_up, 3), "base_range_pct": round((hi - lo) / mid * 100.0, 3),
            "break_pct": round(brk, 3), "mom3_pct": round(mom, 3), "price": round(last, 2)}


def market(bars_by_symbol: Mapping[str, Sequence[float]]) -> tuple[float, float, int] | None:
    """(median move since the open %, share of stocks up, stocks counted) from the latest close of each series."""
    r = [(b[-1] / b[0] - 1.0) * 100.0 for b in bars_by_symbol.values() if len(b) >= 2 and b[0] > 0]
    if len(r) < MIN_STOCKS:
        return None
    return st.median(r), sum(1 for x in r if x > 0) / len(r), len(r)


def evaluate(bars_by_symbol: Mapping[str, Sequence[float]], minute: int) -> list[dict[str, Any]]:
    """Every stock / side that satisfies the rule on the bar that just closed at `minute`. [] while the market numbers are unavailable."""
    mk = market(bars_by_symbol)
    if mk is None:
        return []
    mkt, up, _n = mk
    side = 1 if mkt <= -MARKET_MOVE else -1 if mkt >= MARKET_MOVE else 0
    if side == 0:
        return []
    out = []
    for sym, b in bars_by_symbol.items():
        e = check(b, side, mkt, up)
        if e is not None:
            out.append({"symbol": sym, **e})
    return out


class LiveDetector:
    def __init__(self) -> None:
        self.fired: dict[tuple[str, int], dict[str, Any]] = {}
        self.day = ""

    def update(self, root: Path, day: str, bars: Mapping[str, Sequence[float]], minute: int, t_s: float) -> list[dict[str, Any]]:
        """Run the rule on the live 1-minute closes; log each stock / side the first time it fires today. Returns the new events."""
        if day != self.day:
            self.fired, self.day = {}, day
        new = []
        try:
            for e in evaluate(bars, minute):
                k = (e["symbol"], e["side"])
                if k in self.fired:
                    continue
                e["time"] = f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}"
                self.fired[k] = e
                new.append(e)
            if new:
                p = root / "data" / "base_breaks" / f"{day}.csv"
                p.parent.mkdir(parents=True, exist_ok=True)
                fresh = not p.exists()
                with p.open("a", encoding="utf-8", newline="") as h:
                    w = csv.DictWriter(h, fieldnames=FIELDS)
                    if fresh:
                        w.writeheader()
                    w.writerows([{"date": day, "time": e["time"], "symbol": e["symbol"], "side": e["side"], "ret_open": e["ret_open"], "rs": e["rs"], "mkt": e["mkt"], "breadth_up": e["breadth_up"],
                                  "base_range_pct": e["base_range_pct"], "break_pct": e["break_pct"], "mom3_pct": e["mom3_pct"], "price": e["price"]} for e in new])
            mk = market(bars)
            out = {"day": day, "updated": f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}", "minute": minute, "market": None if mk is None else {"median": round(mk[0], 2), "up": round(mk[1], 3), "n": mk[2]},
                   "events": sorted(self.fired.values(), key=lambda e: e["time"], reverse=True)}
            p = root.joinpath(*LIVE_PATH)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(out), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass
        return new


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
    """bb_ tags for a candidate: bb_fired 1 when this stock has already fired a base break in the candidate's direction today, with its age and numbers."""
    try:
        d = load(root, now.date().isoformat())
        if not d:
            return {}
        side = 1 if str(direction).upper() == "BULLISH" else -1
        e = next((x for x in d["events"] if x["symbol"] == symbol and x["side"] == side), None)
        out: dict[str, Any] = {"bb_fired": int(e is not None), "bb_market_ok": int(d.get("market") is not None and abs(d["market"]["median"]) >= MARKET_MOVE)}
        if e is not None:
            h, m = (int(x) for x in e["time"].split(":")[:2])
            out.update(bb_age_min=max(0, now.hour * 60 + now.minute - (h * 60 + m)), bb_rs=e["rs"], bb_break_pct=e["break_pct"], bb_base_range=e["base_range_pct"])
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


def payload(root: Path = ROOT, today: Any = None) -> dict[str, Any]:
    from datetime import date

    d = load(root, (today or date.today()).isoformat())
    return {"ok": False, "events": []} if not d else {**d, "ok": True}
