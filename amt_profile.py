"""Auction-market-theory levels and cumulative-delta divergence from the live ticks (SHADOW ONLY: events, tags and a review; nothing trades on it).

Auction market theory reads where the market has agreed on price. From every tick (price and the quantity traded) the tracker keeps, per stock and per day:

    volume profile   volume traded at each price bucket (bucket = 0.05 % of the day's first price)
    POC              the bucket with the most volume: the day's fair price so far
    value area       the range around the POC that holds 70 % of the volume (built outward from the POC, each step adding the larger of the next two buckets above / below): VAL .. VAH
    initial balance  the high and low of the first hour (09:15-10:15): a later close beyond it says the day is not just balancing
    30-minute closes the last price of each half hour: ACCEPTANCE = two consecutive closes beyond the value area (the market now treats that price as fair: the next value area is likely further away);
                     REJECTION = price traded beyond VAH / VAL by 0.1 % but the half-hour closed back inside (a failed excursion)
    CVD divergence   cumulative volume delta (buyer- minus seller-initiated volume, tick rule): price makes a new day high at least 0.1 % above the day high of 5+ minutes ago while the cumulative delta is
                     LOWER than it was at that earlier high = bearish divergence (the move is not being bought); a new low 0.1 % under the earlier low with HIGHER cumulative delta = bullish divergence
    day type         range (neither side of the initial balance extended by a quarter of its width), var_up / var_down (one side extended by a quarter to a full width), trend_up / trend_down
                     (one side extended by its full width or more, the other not), wide (both sides extended)

    events    (data/amt_events/<day>.csv)  IB_BREAK_UP / IB_BREAK_DOWN (a 30-minute close beyond the initial balance, once), ACCEPT_ABOVE / ACCEPT_BELOW, REJECT_ABOVE / REJECT_BELOW,
              DIV_HIGH (bearish) / DIV_LOW (bullish), each at most once per stock per 30 minutes
    tags      am_pos_dir (+1 price beyond the value area in the trade's direction, -1 beyond it against, 0 inside)  am_poc_dist_dir (% from the POC, in our direction)  am_va_width_pct
              am_ib_dir (+1 beyond the initial balance with us, -1 against, 0 inside)  am_accept_dir (+1 / -1 accepted outside value with / against us, 0 none)  am_div_dir (+1 a divergence in the
              last 30 minutes favours the trade, -1 opposes it, 0 none)  am_daytype  am_ib_ext_dir (how far past the IB with us, in IB widths)

    python amt_profile.py replay YYYY-MM-DD    rebuild the day's events from the recorded ticks and review them (needs the ts, ltp, tq and side tick columns)
    python amt_profile.py review [YYYY-MM-DD]  what the stocks did after each event, against the market (5 / 15 / 30 / 60 minutes)
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OPEN_S = 9 * 3600 + 15 * 60
IB_END_S = OPEN_S + 3600
PERIOD_S = 1800
BUCKET_PCT = 0.05
VA_SHARE = 0.70
REJECT_PCT = 0.1
DIV_GAP_S = 300
DEBOUNCE_S = 1800
WRITE_EVERY_S = 20.0
LIVE_PATH = ("data", "ticks", "amt_live.json")
FIELDS = ["date", "time", "symbol", "kind", "price", "poc", "vah", "val", "ib_hi", "ib_lo"]
BULL = {"IB_BREAK_UP", "ACCEPT_ABOVE", "REJECT_BELOW", "DIV_LOW"}


def value_area(profile: dict[int, float], p0: float, w: float) -> tuple[float, float, float] | None:
    """(VAL, POC, VAH) prices of the 70 % value area from a {bucket index: volume} profile. None for an empty profile.
    Built outward from the POC over the traded price levels in order (a gap in the profile is skipped, not counted): each step adds the larger of the next two levels above / below."""
    total = sum(profile.values())
    if total <= 0:
        return None
    keys = sorted(profile)
    vals = [profile[k] for k in keys]
    poc = max(range(len(keys)), key=lambda i: (vals[i], -abs(keys[i])))
    lo = hi = poc
    acc = vals[poc]
    while acc < VA_SHARE * total:
        up = vals[hi + 1:hi + 3]
        dn = vals[max(0, lo - 2):lo]
        if not up and not dn:
            break
        if sum(up) >= sum(dn) and up:
            acc += sum(up)
            hi += len(up)
        else:
            acc += sum(dn)
            lo -= len(dn)
    price = lambda k: p0 + k * w
    return price(keys[lo]), price(keys[poc]), price(keys[hi])


class _S:
    __slots__ = ("p0", "w", "prof", "hi", "lo", "ib_hi", "ib_lo", "cum", "cvd_at_hi", "cvd_at_lo", "t_hi", "t_lo", "period", "closes", "ltp", "last", "ib_done", "ib_break", "div", "accept", "va", "hi_hist", "lo_hist", "last_min")

    def __init__(self, p0: float) -> None:
        self.p0, self.w = p0, p0 * BUCKET_PCT / 100.0
        self.prof: dict[int, float] = {}
        self.hi = self.lo = self.ib_hi = self.ib_lo = p0
        self.cum = 0.0
        self.cvd_at_hi = self.cvd_at_lo = 0.0
        self.t_hi = self.t_lo = 0.0
        self.period = 0
        self.closes: list[float] = []
        self.ltp = p0
        self.last: dict[str, float] = {}
        self.ib_done = False
        self.ib_break = 0                    # +1 / -1 once a 30-minute close has been beyond the initial balance
        self.div = (0, 0.0)                  # (+1 bullish / -1 bearish, time)
        self.accept = 0
        self.va: tuple[float, float, float] | None = None
        self.hi_hist: list[tuple[float, float, float]] = []          # once a minute: (time, day high, cumulative delta when it was made)
        self.lo_hist: list[tuple[float, float, float]] = []
        self.last_min = -1


class AMTTracker:
    def __init__(self) -> None:
        self.state: dict[str, _S] = {}
        self._written = -1e9

    def update(self, sym: str, t_s: float, ltp: float, qty: float, side: str) -> list[dict[str, Any]]:
        """One tick. Returns the events it produced (usually none)."""
        if t_s < OPEN_S or ltp <= 0:
            return []
        s = self.state.get(sym)
        if s is None:
            s = self.state[sym] = _S(ltp)
        out: list[dict[str, Any]] = []
        period = int((t_s - OPEN_S) // PERIOD_S)
        if period > s.period:                                         # a half-hour just closed: judge it with the last price before this tick
            s.closes.append(s.ltp)
            s.period = period
            out += self._half_hour(sym, s, t_s)
        if qty > 0:
            k = round((ltp - s.p0) / s.w)
            s.prof[k] = s.prof.get(k, 0.0) + qty
            if side in ("B", "S"):
                s.cum += qty if side == "B" else -qty
        s.ltp = ltp
        if t_s < IB_END_S:
            s.ib_hi, s.ib_lo = max(s.ib_hi, ltp), min(s.ib_lo, ltp)
        elif not s.ib_done:
            s.ib_done = True
        minute = int(t_s // 60)
        if minute != s.last_min:                                       # remember where the day's high / low and the cumulative delta stood, once a minute, for 15 minutes
            s.last_min = minute
            s.hi_hist.append((t_s, s.hi, s.cvd_at_hi))
            s.lo_hist.append((t_s, s.lo, s.cvd_at_lo))
            del s.hi_hist[:-15], s.lo_hist[:-15]
        if ltp > s.hi:
            ref = next((h for h in reversed(s.hi_hist) if t_s - h[0] >= DIV_GAP_S), None)
            if ref is not None and ltp >= ref[1] * 1.001 and s.cum < ref[2]:
                out += self._event(sym, s, t_s, "DIV_HIGH")
                if out and out[-1]["kind"] == "DIV_HIGH":
                    s.div = (-1, t_s)
            s.hi, s.cvd_at_hi, s.t_hi = ltp, s.cum, t_s
        if ltp < s.lo:
            ref = next((h for h in reversed(s.lo_hist) if t_s - h[0] >= DIV_GAP_S), None)
            if ref is not None and ltp <= ref[1] * 0.999 and s.cum > ref[2]:
                out += self._event(sym, s, t_s, "DIV_LOW")
                if out and out[-1]["kind"] == "DIV_LOW":
                    s.div = (1, t_s)
            s.lo, s.cvd_at_lo, s.t_lo = ltp, s.cum, t_s
        return out

    def _event(self, sym: str, s: _S, t_s: float, kind: str) -> list[dict[str, Any]]:
        if t_s - s.last.get(kind, -1e9) < DEBOUNCE_S:
            return []
        s.last[kind] = t_s
        va = s.va or value_area(s.prof, s.p0, s.w) or (0.0, 0.0, 0.0)
        return [{"time": f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}", "symbol": sym, "kind": kind, "price": round(s.ltp, 2), "poc": round(va[1], 2), "vah": round(va[2], 2),
                 "val": round(va[0], 2), "ib_hi": round(s.ib_hi, 2), "ib_lo": round(s.ib_lo, 2), "t": t_s}]

    def _half_hour(self, sym: str, s: _S, t_s: float) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        va = value_area(s.prof, s.p0, s.w)
        s.va = va
        if va is None:
            return out
        val, poc, vah = va
        close = s.closes[-1]
        if s.ib_done and s.ib_break == 0:
            if close > s.ib_hi:
                s.ib_break = 1
                out += self._event(sym, s, t_s, "IB_BREAK_UP")
            elif close < s.ib_lo:
                s.ib_break = -1
                out += self._event(sym, s, t_s, "IB_BREAK_DOWN")
        if len(s.closes) >= 2:
            prev = s.closes[-2]
            if close > vah and prev > vah:
                s.accept = 1
                out += self._event(sym, s, t_s, "ACCEPT_ABOVE")
            elif close < val and prev < val:
                s.accept = -1
                out += self._event(sym, s, t_s, "ACCEPT_BELOW")
            else:
                s.accept = 0
        if val <= close <= vah:                                        # back inside: was there an excursion this half hour?
            if s.hi >= vah * (1 + REJECT_PCT / 100.0) and max(s.ltp, close) <= vah * 1.0005:
                out += self._event(sym, s, t_s, "REJECT_ABOVE")
            if s.lo <= val * (1 - REJECT_PCT / 100.0) and min(s.ltp, close) >= val * 0.9995:
                out += self._event(sym, s, t_s, "REJECT_BELOW")
        return out

    def daytype(self, s: _S) -> tuple[str, float, float]:
        width = max(s.ib_hi - s.ib_lo, s.p0 * 0.0005)
        up, dn = max(0.0, (s.hi - s.ib_hi) / width), max(0.0, (s.ib_lo - s.lo) / width)
        kind = ("range" if up < 0.25 and dn < 0.25 else "trend_up" if up >= 1.0 and dn < 0.25 else "trend_down" if dn >= 1.0 and up < 0.25 else "var_up" if up >= 0.25 and dn < 0.25
                else "var_down" if dn >= 0.25 and up < 0.25 else "wide")
        return kind, up, dn

    def snapshot(self, t_s: float) -> dict[str, Any]:
        out = {}
        for sym, s in self.state.items():
            va = value_area(s.prof, s.p0, s.w)
            if va is None:
                continue
            val, poc, vah = va
            kind, up, dn = self.daytype(s)
            out[sym] = {"ltp": round(s.ltp, 2), "val": round(val, 2), "poc": round(poc, 2), "vah": round(vah, 2), "ib_hi": round(s.ib_hi, 2), "ib_lo": round(s.ib_lo, 2), "ib_done": s.ib_done,
                        "ib_break": s.ib_break, "accept": s.accept, "div": [s.div[0], round(s.div[1])], "daytype": kind, "ib_up": round(up, 2), "ib_dn": round(dn, 2)}
        return out

    def maybe_write(self, root: Path, day: str, t_s: float, wall: float, events: list[dict[str, Any]]) -> bool:
        if events:
            p = root / "data" / "amt_events" / f"{day}.csv"
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
        s = d["stocks"].get(symbol) if d else None
        if not s:
            return {}
        sign = 1 if str(direction).upper() == "BULLISH" else -1
        px = s["ltp"]
        pos = 1 if px > s["vah"] else -1 if px < s["val"] else 0
        now_s = now.hour * 3600 + now.minute * 60 + now.second
        div = s["div"][0] if s["div"][1] and now_s - s["div"][1] <= 1800 else 0
        ibx = 1 if px > s["ib_hi"] else -1 if px < s["ib_lo"] else 0
        width = max(s["ib_hi"] - s["ib_lo"], 1e-9)
        ext = (px - s["ib_hi"]) / width if px > s["ib_hi"] else (px - s["ib_lo"]) / width if px < s["ib_lo"] else 0.0
        return {"am_pos_dir": sign * pos, "am_poc_dist_dir": round(sign * (px / s["poc"] - 1.0) * 100.0, 2), "am_va_width_pct": round((s["vah"] - s["val"]) / s["poc"] * 100.0, 2),
                "am_ib_dir": sign * ibx if s["ib_done"] else 0, "am_ib_ext_dir": round(sign * ext, 2) if s["ib_done"] else 0.0, "am_accept_dir": sign * s["accept"], "am_div_dir": sign * div,
                "am_daytype": s["daytype"]}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


# --- replay and review -----------------------------------------------------------------------------------------------------------------------------------------------------------
def _secs(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def replay_day(root: Path, day: str) -> list[dict[str, Any]]:
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
        tr = AMTTracker()
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
    log = root / "data" / "amt_events" / f"{day}.csv"
    if log.exists() and not force_replay:
        with log.open(encoding="utf-8", newline="") as h:
            evs = [{"time": r["time"], "symbol": r["symbol"], "kind": r["kind"]} for r in csv.DictReader(h)]
        source = "live event log"
    else:
        evs = replay_day(root, day)
        source = "replayed from ticks"
    if not evs:
        return None
    samples = rs_replay.load_samples(root, day)
    if not samples:
        return None
    series = rs_replay.series_by_symbol(samples)
    events = [{"time": e["time"], "symbol": e["symbol"], "kind": ("LEADER_" if e["kind"] in BULL else "LAGGARD_") + e["kind"]} for e in evs]
    rows = rs_replay.forward_moves(events, series, day)
    table = rs_replay._group(rows, lambda r: r["kind"])
    folder = root / "data" / "amt_events"
    folder.mkdir(parents=True, exist_ok=True)
    L = [f"# Auction-market-theory events, {day} ({source})", "", f"{len(evs)} events. Excess = the stock's move in the event's direction (bullish events up, bearish down) minus the median stock's over the same minutes, stock level.", ""]
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
    raise SystemExit(main())
