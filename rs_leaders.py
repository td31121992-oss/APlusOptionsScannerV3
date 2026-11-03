"""Red-market leaders: which stocks are outperforming the market RIGHT NOW, found tick by tick (SHADOW / DISPLAY: nothing here trades).

In a falling market the stocks that hold up or rise are what a trader wants to see, and nobody finds them by hand among 213. The tick recorder hands every packet to an RSTracker (O(1) per
tick); once a second it works out, for every stock,

    move       % from the previous close (NSE daily file)           market median   the median stock's move: the "market" (no index feed needed, it reacts as the stocks do)
    rs         move minus the market median: how far ahead of / behind the market the stock is
    vs_vwap    % above / below the exchange's own VWAP (avg_price in the packet)       rvol   volume so far vs the stock's usual volume for this time of day (event_tags.expected_fraction)
    mom15      the stock's move over the last 15 minutes

and every 2 seconds writes data/ticks/rs_live.json (what the /rs-leaders page and the shadow tags read). The market is RED when the median stock is at or below RED_MEDIAN_PCT (-0.3 %) or at
least RED_DOWN_PCT (65 %) of stocks are down. A LEADER is a stock with rs >= LEADER_RS (2.0) trading above VWAP on rvol >= MIN_RVOL (1.0); STRONG at rs >= 3. LAGGARDS are the mirror (rs <= -2, below VWAP).
Each stock that newly becomes a leader / laggard in a red market, or a leader in a green one, is logged once per 30 minutes to data/rs_events/<day>.csv.

    rs_vs_market_dir   (tag) the stock's rs in OUR direction (a call wants a positive number, a put a negative rs, shown positive)      rs_red   1 when the market is red
    rs_leader / rs_laggard   (tag) 1 when the stock is a leader / laggard now      rs_rank   its rank among the leaders (calls) / laggards (puts), 1 = strongest

Evidence so far (12 days of 5-minute data, 26 red-market snapshots): leaders of 3 % or more beat the market by about +0.3 % by the close (71 % of them), and by nothing over the next 30 minutes;
calls on leaders were about break-even (20 signals) and calls overall lost in red markets. So this shows leaders quickly and records how they do; it does not claim they are a signal.
"""

from __future__ import annotations

import csv
import json
import os
import statistics as st
import threading
import time
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
RED_MEDIAN_PCT, RED_DOWN_PCT = -0.3, 65.0
LEADER_RS, STRONG_RS, MIN_RVOL = 2.0, 3.0, 1.0
MIN_STOCKS = 100
STALE_S, ACC_S, CHASE_MOM = 10.0, 110.0, 1.5       # a last tick older than STALE_S is not shown; acceleration = move over the last ~2 minutes; "chasing" = already ran 1.5 % in 15 minutes
MAX_STOCK_SPREAD, MAX_OPT_SPREAD, SECTOR_MIN = 0.25, 2.0, 4     # stock bid-ask % / ATM option bid-ask % (the option_selector limit) / members needed for a sector median
WRITE_EVERY, COMPUTE_EVERY = 2.0, 1.0
ALL_EVERY = 5.0
LOG_EVERY_MIN = 30
TOP_N = 15
MOM_SAMPLE_S, MOM_WINDOW_S = 5.0, 15 * 60
NIFTY_ID = 13
SECTOR_INDEX = {"IT": 29, "Auto": 14, "Pharma/Healthcare": 32, "FMCG/Consumer": 28, "Metals": 31, "Energy/Oil & Gas": 42, "Banking/Financial Services": 27}     # our sector label -> Dhan index id (index_strip.py)
INDEX_IDS = [NIFTY_ID] + sorted(set(SECTOR_INDEX.values()))
OPEN_S = 9 * 3600 + 15 * 60                         # ticks before the open are pre-open auction prices: not part of the board
EVENT_FIELDS = ["date", "time", "symbol", "kind", "move_pct", "rs", "vs_vwap_pct", "rvol", "ltp", "market_median", "pct_down", "rs_nifty", "rs_sec", "acc2", "checks_ok", "failed",
                "lag_s", "compute_ms", "since_rs1_s", "first"]     # last three = detection latency (see rs_replay.py)


def _secs(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


class IndexLog:
    """data/ticks/<day>/index_ticks.csv: ts,id,kind,value (kind L = last price, at most one a second per index; P = previous close). Lets rs_replay.py replay the index comparisons."""

    def __init__(self, root: Path, day: str) -> None:
        self.path = root / "data" / "ticks" / day / "index_ticks.csv"
        self._last: dict[int, float] = {}
        self._h = None

    def write(self, sid: int, kind: str, value: float, ts: str, now_s: float) -> None:
        if kind == "L" and now_s - self._last.get(sid, -1e9) < 1.0:
            return
        self._last[sid] = now_s
        if self._h is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.exists()
            self._h = self.path.open("a", encoding="utf-8", newline="")
            if new:
                self._h.write("ts,id,kind,value\n")
        self._h.write(f"{ts},{sid},{kind},{value}\n")
        if kind == "P" or now_s % 5 < 1.0:
            self._h.flush()

    def close(self) -> None:
        if self._h is not None:
            self._h.close()
            self._h = None


def wall_clock_ok(now_s: float, newest_tick_s: float) -> bool:
    """Latency against the wall clock only means something when the board is running on the live tick stream (not a test or a replay with its own clock)."""
    return abs(now_s - newest_tick_s) < 1.0


def load_reference(root: Path, day: str) -> dict[str, dict[str, float]]:
    """symbol -> {prev_close, avg_vol20} from the NSE daily file (the last trading day before `day`, and the 20 days up to it)."""
    rows: dict[str, list[tuple[str, float, float]]] = {}
    try:
        with (root / "data" / "nse_daily" / "stock_daily.csv").open(encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                try:
                    rows.setdefault(r["symbol"], []).append((r["day"], float(r["close"]), float(r["ttl_qty"])))
                except (KeyError, ValueError):
                    continue
    except OSError:
        return {}
    out = {}
    for sym, v in rows.items():
        v = sorted(x for x in v if x[0] < day)
        if v:
            out[sym] = {"prev_close": v[-1][1], "avg_vol20": st.mean(q for _d, _c, q in v[-20:])}
    return out


class _S:
    __slots__ = ("ltp", "vol", "vwap", "samples", "last_sample", "t", "bid", "ask")

    def __init__(self) -> None:
        self.ltp = self.vol = self.vwap = self.t = self.bid = self.ask = 0.0
        self.samples: deque[tuple[float, float]] = deque()
        self.last_sample = -1e9


class RSTracker:
    def __init__(self, reference: Mapping[str, Mapping[str, float]], sectors: Mapping[str, str] | None = None) -> None:
        self.ref = reference
        self.sectors = sectors or {}
        self.state: dict[str, _S] = {}
        self.t = 0.0
        self._computed = self._written = -1e9
        self._snap: dict[str, Any] | None = None
        self._logged: dict[tuple[str, str], float] = {}
        self.indices: dict[int, dict[str, float]] = {}     # Dhan index id -> {"ltp", "prev"}: NIFTY 50 and the sector indices from the same feed
        self._cross: dict[str, float] = {}                  # symbol -> when |rs| first reached 1 % (and has stayed above 0.5 % since): the start of the move as the board sees it
        self._compute_ms = 0.0
        self._all_written = -1e9
        self._seen: set[tuple[str, str]] = set()           # (symbol, LEADER / LAGGARD) already flagged today: only the first flag measures detection latency

    @property
    def nifty(self) -> float:
        return self.indices.get(NIFTY_ID, {}).get("ltp", 0.0)

    @property
    def nifty_prev(self) -> float:
        return self.indices.get(NIFTY_ID, {}).get("prev", 0.0)

    def set_index(self, ltp: float = 0.0, prev: float = 0.0, sid: int = NIFTY_ID) -> None:
        """An index's last price and / or previous close (NIFTY 50 by default). Without both, that index's comparison is simply left out."""
        d = self.indices.setdefault(int(sid), {})
        if ltp > 0:
            d["ltp"] = ltp
        if prev > 0:
            d["prev"] = prev

    def index_move(self, sid: int) -> float | None:
        d = self.indices.get(int(sid)) or {}
        return (d["ltp"] / d["prev"] - 1.0) * 100.0 if d.get("ltp", 0) > 0 and d.get("prev", 0) > 0 else None

    def update(self, sym: str, ts: str, ltp: float, volume: float, vwap: float, bid: float = 0.0, ask: float = 0.0) -> None:
        """One tick: price, cumulative day volume, the exchange's VWAP and the best bid / ask. O(1)."""
        if ltp <= 0 or sym not in self.ref:
            return
        t = _secs(ts)
        if t < OPEN_S:
            return
        s = self.state.get(sym)
        if s is None:
            s = self.state[sym] = _S()
        s.ltp, s.vol, s.t = ltp, max(s.vol, volume), t
        if bid > 0 and ask >= bid:
            s.bid, s.ask = bid, ask
        if vwap > 0:
            s.vwap = vwap
        self.t = max(self.t, t)
        if t - s.last_sample >= MOM_SAMPLE_S:
            s.last_sample = t
            s.samples.append((t, ltp))
            while s.samples and t - s.samples[0][0] > MOM_WINDOW_S + 60:
                s.samples.popleft()

    def compute(self, now_s: float) -> dict[str, Any] | None:
        from event_tags import expected_fraction

        rows = []
        for sym, s in self.state.items():
            ref = self.ref[sym]
            if ref["prev_close"] <= 0:
                continue
            move = (s.ltp / ref["prev_close"] - 1.0) * 100.0
            frac = expected_fraction(now_s / 60.0 - (9 * 60 + 15))
            rvol = s.vol / (ref["avg_vol20"] * frac) if ref["avg_vol20"] > 0 and frac > 0.01 else 0.0
            old = next((p for t, p in s.samples if now_s - t <= MOM_WINDOW_S), None)
            ref2 = next((p for t, p in reversed(s.samples) if now_s - t >= ACC_S), None)
            rows.append({"s": sym, "sec": self.sectors.get(sym, ""), "ltp": round(s.ltp, 2), "move": move, "age": max(0.0, now_s - s.t), "acc2": (s.ltp / ref2 - 1.0) * 100.0 if ref2 else 0.0,
                         "spread": (s.ask - s.bid) / s.ask * 100.0 if s.ask > 0 else None, "vs_vwap": (s.ltp / s.vwap - 1.0) * 100.0 if s.vwap > 0 else 0.0,
                         "rvol": rvol, "mom15": (s.ltp / old - 1.0) * 100.0 if old else 0.0})
        if len(rows) < MIN_STOCKS:
            return None
        med = st.median(r["move"] for r in rows)
        down = 100.0 * sum(1 for r in rows if r["move"] < 0) / len(rows)
        red = med <= RED_MEDIAN_PCT or down >= RED_DOWN_PCT
        for r in rows:
            if abs(r["move"] - med) >= 1.0:
                self._cross.setdefault(r["s"], now_s)
            elif abs(r["move"] - med) < 0.5:
                self._cross.pop(r["s"], None)
        by_sec: dict[str, list[float]] = {}
        for r in rows:
            by_sec.setdefault(r["sec"], []).append(r["move"])
        sec_med = {k: st.median(v) for k, v in by_sec.items() if k and len(v) >= SECTOR_MIN}
        nifty = self.index_move(NIFTY_ID)
        sec_idx = {name: m for name, sid in SECTOR_INDEX.items() if (m := self.index_move(sid)) is not None}
        for r in rows:
            r["rs"] = r["move"] - med
            r["rs_nifty"] = r["move"] - nifty if nifty is not None else None
            r["rs_sec"] = r["move"] - sec_med[r["sec"]] if r["sec"] in sec_med else None      # vs its own sector (None: sector too small / unknown)
            r["rs_sidx"] = r["move"] - sec_idx[r["sec"]] if r["sec"] in sec_idx else None     # vs the sector INDEX where we stream one
        fresh = [r for r in rows if r["age"] <= STALE_S]                                    # a stock whose last tick is old is not a "right now" signal
        leaders = sorted((r for r in fresh if r["rs"] >= LEADER_RS and r["vs_vwap"] > 0 and r["rvol"] >= MIN_RVOL), key=lambda r: -r["rs"])
        laggards = sorted((r for r in fresh if r["rs"] <= -LEADER_RS and r["vs_vwap"] < 0 and r["rvol"] >= MIN_RVOL), key=lambda r: r["rs"])
        for sign, group in ((1.0, leaders), (-1.0, laggards)):
            for r in group:                                                                 # validation labels (shadow: they never remove a stock from the list)
                chk = {"nifty": r["rs_nifty"] is None or sign * r["rs_nifty"] > 0, "sector": (r["rs_sidx"] if r["rs_sidx"] is not None else r["rs_sec"]) is None or sign * (r["rs_sidx"] if r["rs_sidx"] is not None else r["rs_sec"]) > 0, "accel": sign * r["acc2"] >= 0, "chase": sign * r["mom15"] < CHASE_MOM,
                       "spread": r["spread"] is None or r["spread"] <= MAX_STOCK_SPREAD}
                r["checks"] = chk
                r["ok"] = all(chk.values())
        rnd = lambda r: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items() if k != "age"}
        return {"market": {"median": round(med, 2), "nifty": None if nifty is None else round(nifty, 2), "sector_idx": {k: round(v, 2) for k, v in sec_idx.items()}, "pct_down": round(down, 1), "red": bool(red), "n": len(rows)}, "leaders": [rnd(r) for r in leaders[:TOP_N]], "laggards": [rnd(r) for r in laggards[:TOP_N]],
                "n_leaders": len(leaders), "n_laggards": len(laggards), "_all_leaders": leaders, "_all_laggards": laggards, "_rows": rows}

    def events(self, snap: Mapping[str, Any], now_s: float, day: str, lag_s: float | None = None) -> list[dict[str, Any]]:
        out = []
        for kind, rows in (("LEADER", snap["_all_leaders"]), ("LAGGARD", snap["_all_laggards"])):
            for r in rows:
                k = "STRONG_" + kind if abs(r["rs"]) >= STRONG_RS else kind
                last = self._logged.get((r["s"], k))
                if (kind == "LAGGARD" and not snap["market"]["red"]) or (last is not None and now_s - last < LOG_EVERY_MIN * 60):
                    continue
                self._logged[(r["s"], k)] = now_s
                first = (r["s"], kind) not in self._seen
                self._seen.add((r["s"], kind))
                out.append({"date": day, "time": f"{int(now_s // 3600):02d}:{int(now_s % 3600 // 60):02d}:{int(now_s % 60):02d}", "symbol": r["s"], "kind": k, "move_pct": round(r["move"], 2), "rs": round(r["rs"], 2),
                            "vs_vwap_pct": round(r["vs_vwap"], 2), "rvol": round(r["rvol"], 1), "ltp": round(r["ltp"], 2), "market_median": snap["market"]["median"], "pct_down": snap["market"]["pct_down"],
                            "rs_nifty": None if r.get("rs_nifty") is None else round(r["rs_nifty"], 2), "rs_sec": None if r.get("rs_sec") is None else round(r["rs_sec"], 2), "acc2": round(r["acc2"], 2),
                            "checks_ok": r.get("ok"), "failed": ",".join(k for k, v in (r.get("checks") or {}).items() if not v), "lag_s": None if lag_s is None else round(lag_s, 2),
                            "compute_ms": round(self._compute_ms, 2), "since_rs1_s": round(now_s - self._cross.get(r["s"], now_s), 1), "first": int(first)})
        return out

    def _write_all(self, root: Path, day: str, now_s: float) -> None:
        """data/ticks/rs_all.json: every stock's live numbers (short keys), for the Breakouts & Breakdowns board."""
        snap = self._snap or {}
        rows = {r["s"]: {"m": round(r["move"], 3), "rs": round(r["rs"], 3), "vw": round(r["vs_vwap"], 3), "rv": round(r["rvol"], 2), "a2": round(r["acc2"], 3), "ltp": round(r["ltp"], 2), "sec": r["sec"],
                         "rss": None if r.get("rs_sec") is None else round(r["rs_sec"], 3), "rsi": None if r.get("rs_sidx") is None else round(r["rs_sidx"], 3)}
                for r in snap.get("_rows", []) if r.get("age", 0) <= STALE_S * 3}
        out = {"day": day, "updated": f"{int(now_s // 3600):02d}:{int(now_s % 3600 // 60):02d}:{int(now_s % 60):02d}", "market": snap.get("market", {}), "stocks": rows}
        path = root / "data" / "ticks" / "rs_all.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(out), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass

    def maybe_write(self, root: Path, day: str, wall: float | None = None, now_s: float | None = None) -> bool:
        """Compute at most once a second and write the live file every 2 seconds. Returns True when a file was written."""
        wall = time.monotonic() if wall is None else wall
        now_s = self.t if now_s is None else now_s
        if wall - self._computed >= COMPUTE_EVERY:
            self._computed = wall
            t0 = time.perf_counter()
            self._snap = self.compute(now_s)
            self._compute_ms = (time.perf_counter() - t0) * 1000.0
        if self._snap is not None and wall - self._all_written >= ALL_EVERY:
            self._all_written = wall
            self._write_all(root, day, now_s)
        if self._snap is None or wall - self._written < WRITE_EVERY:
            return False
        self._written = wall
        snap = {k: v for k, v in self._snap.items() if not k.startswith("_")}
        snap["compute_ms"] = round(self._compute_ms, 2)
        snap.update(day=day, updated=f"{int(now_s // 3600):02d}:{int(now_s % 3600 // 60):02d}:{int(now_s % 60):02d}")
        path = root / "data" / "ticks" / "rs_live.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap), encoding="utf-8")
            os.replace(tmp, path)
            now = datetime.now()
            lag = (now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6) - self.t if wall_clock_ok(now_s, self.t) else None   # wall clock minus the newest tick
            ev = self.events(self._snap, now_s, day, lag)
            if ev:
                p = root / "data" / "rs_events" / f"{day}.csv"
                p.parent.mkdir(parents=True, exist_ok=True)
                new = not p.exists()
                with p.open("a", encoding="utf-8", newline="") as h:
                    w = csv.DictWriter(h, fieldnames=EVENT_FIELDS)
                    if new:
                        w.writeheader()
                    w.writerows(ev)
        except OSError:
            return False
        return True


_CACHE: dict[str, Any] = {"mtime": None, "data": None}


def load(root: Path, day: str) -> dict[str, Any] | None:
    path = root / "data" / "ticks" / "rs_live.json"
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
    """Shadow tags for a candidate from the live file. {} when the file is missing, stale (another day) or the stock is not in it."""
    try:
        snap = load(root, now.date().isoformat())
        if not snap:
            return {}
        sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
        mk = snap["market"]
        out: dict[str, Any] = {"rs_nifty_move": mk.get("nifty"), "rs_red": int(mk["red"]), "rs_market_median": mk["median"], "rs_pct_down": mk["pct_down"]}
        lead = [r["s"] for r in snap.get("leaders", [])]
        lag = [r["s"] for r in snap.get("laggards", [])]
        out["rs_leader"], out["rs_laggard"] = int(symbol in lead), int(symbol in lag)
        mine = lead if sign > 0 else lag
        if symbol in mine:
            out["rs_rank"] = mine.index(symbol) + 1
        row = next((r for r in snap.get("leaders", []) + snap.get("laggards", []) if r["s"] == symbol), None)
        if row:
            out["rs_vs_market_dir"] = round(sign * row["rs"], 2)
            if row.get("rs_nifty") is not None:
                out["rs_vs_nifty_dir"] = round(sign * row["rs_nifty"], 2)
            if row.get("rs_sidx") is not None:
                out["rs_vs_sector_idx_dir"] = round(sign * row["rs_sidx"], 2)
            if row.get("rs_sec") is not None:
                out["rs_vs_sector_dir"] = round(sign * row["rs_sec"], 2)
            out["rs_accel2_dir"] = round(sign * row.get("acc2", 0.0), 2)
            out["rs_checks_pass"] = int(bool(row.get("ok")))
            out["rs_failed"] = ",".join(k for k, v in (row.get("checks") or {}).items() if not v)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}


_CHAIN: dict[str, Any] = {"at": 0.0, "day": "", "data": {}}


def chain_check(root: Path, day: str, wall: float | None = None, every: float = 120.0) -> dict[str, dict[str, Any]]:
    """symbol -> ATM option spreads from the latest option-chain snapshot of the day (data/options_intelligence_upstox). Rescanned at most every `every` seconds (the whole day's file takes
    about a second) and only by the dashboard, never on the tick path. ok_ce / ok_pe = that side quotes a bid and ask within MAX_OPT_SPREAD %."""
    import gzip

    wall = time.monotonic() if wall is None else wall
    if _CHAIN["day"] == day and wall - _CHAIN["at"] < every:
        return _CHAIN["data"]
    latest: dict[str, dict[str, Any]] = {}
    try:
        with gzip.open(root / "data" / "options_intelligence_upstox" / day / "option_chain_rows.csv.gz", "rt", encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                sym, cap = r.get("symbol"), r.get("captured_at") or ""
                if not sym:
                    continue
                cur = latest.get(sym)
                if cur is None or cap > cur["cap"]:
                    cur = latest[sym] = {"cap": cap, "rows": []}
                if cap == cur["cap"]:
                    cur["rows"].append(r)
    except (OSError, EOFError, ValueError):
        pass
    out: dict[str, dict[str, Any]] = {}
    for sym, v in latest.items():
        try:
            spot = float(v["rows"][0]["spot"])
            atm = min({float(r["strike"]) for r in v["rows"]}, key=lambda k: abs(k - spot))
            sp: dict[str, Any] = {}
            for r in v["rows"]:
                if float(r["strike"]) == atm:
                    bid, ask = float(r["bid"] or 0), float(r["ask"] or 0)
                    sp[r["side"]] = round((ask - bid) / ask * 100.0, 2) if bid > 0 and ask >= bid else None
            out[sym] = {"ce_spread": sp.get("CE"), "pe_spread": sp.get("PE"), "at": v["cap"][11:19],
                        "ok_ce": sp.get("CE") is not None and sp["CE"] <= MAX_OPT_SPREAD, "ok_pe": sp.get("PE") is not None and sp["PE"] <= MAX_OPT_SPREAD}
        except (ValueError, KeyError, TypeError):
            continue
    _CHAIN.update(at=wall, day=day, data=out)
    return out


def payload(root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    """JSON for the /rs-leaders page: the live file plus big-print net buying per stock."""
    day = (today or date.today()).isoformat()
    snap = load(root, day)
    if not snap:
        return {"ok": False, "error": "no live data yet today (the tick recorder runs 09:05-15:32; needs about 100 stocks with ticks)"}
    out = dict(snap, ok=True)
    try:
        import big_prints

        bp = (big_prints.load(root, day) or {}).get("stocks") or {}
        for key in ("leaders", "laggards"):
            for r in out.get(key, []):
                r["big15"] = (bp.get(r["s"]) or {}).get("net15_cr")
    except Exception:                                      # noqa: BLE001
        pass
    try:
        chain = chain_check(root, day)
        for key, side in (("leaders", "ce"), ("laggards", "pe")):                            # a leader is a call candidate, a laggard a put candidate
            for r in out.get(key, []):
                c = chain.get(r["s"])
                r["opt_spread"] = None if not c else c[f"{side}_spread"]
                r["chain_ok"] = None if not c else bool(c[f"ok_{side}"])
                if r.get("checks") is not None and r["chain_ok"] is not None:
                    r["checks"]["chain"] = r["chain_ok"]
                    r["ok"] = all(r["checks"].values())
    except Exception:                                      # noqa: BLE001 - the chain check is extra information only
        pass
    return out
