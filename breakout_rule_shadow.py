"""Breakout / breakdown rule check (SHADOW ONLY: signals and outcomes in files; nothing trades on it).

The rule, as given:

    BREAKOUT (long)   5-minute close crosses above the previous day's high OR the 15-minute opening-range high; volume > 1.5 x the average of the last 20 candles; close above VWAP;
                      EMA 9 above EMA 20 (5-minute); RSI(14) above 60; gap between 0 % and +3 %; liquid F&O stock (average daily volume above 5 lakh shares).
    BREAKDOWN (short) the mirror: close below the previous day's low OR the opening-range low; volume > 1.5 x average; close below VWAP; EMA 9 below EMA 20; RSI below 40; gap between 0 % and -3 %.

Everything is computed from the stock's 5-minute candles (Dhan intraday chart, with volume), continuous across days for the EMAs, RSI and the 20-candle volume average; VWAP restarts each day. The opening range is the
first three candles (09:15 - 09:30), so a signal needs a candle at 09:30 or later; the last signal candle is 14:40. "Crosses": the previous candle's close was on the other side of the level. First signal per stock, side and day.

Each signal is followed on the nearest-the-money option of the right side for the nearest expiry (call for a breakout, put for a breakdown): bought at the OPEN of the candle after the signal (+1 %), the live exit ladder replayed on
its 5-minute candles (baseline_replay.simulate: -20 % stop, the +5 / +10 / +20 / +30 % locks, session end; Rs 250 charges; Rs 20,000 a trade).

    data/breakout_rule/signals.csv   one row per signal: day, stock, side, time, level crossed, the indicator values, option, entry, peak %, exit, why, net Rs
    data/breakout_rule/review.md     counts, share that never reached +1 % / +40 %, ladder result, by side, by day; and how many of the 3 % movers of the capture funnel the rule flagged in time

    python breakout_rule_shadow.py [YYYY-MM-DD ...]   fetch what is missing, rebuild those days (default: every day from 1 Oct) and the review
"""

from __future__ import annotations

import csv
import json
import os
import statistics as st
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
CACHE = Path(os.getenv("APLUS_SHADOW_CACHE", r"E:\APlusData\shadow_cache" if Path("E:/").exists() else str(ROOT / "data" / "shadow_cache")))
FOLDER = ("data", "breakout_rule")
START_DAY = "2026-10-01"
VOL_MULT, RSI_LONG, RSI_SHORT, GAP_MAX, MIN_AVG_VOL = 1.5, 60.0, 40.0, 3.0, 500_000
FIRST_MIN, LAST_MIN = 9 * 60 + 30, 14 * 60 + 40
FIELDS = ["day", "symbol", "side", "time", "level", "level_kind", "close", "vol_x", "rsi", "gap_pct", "strike", "option", "entry", "peak_pct", "exit", "why", "gross_pct", "net_rs"]


# ---------------------------------------------------------------- indicators --------------------------------------------------------------------
def ema(values: Sequence[float], n: int) -> list[float]:
    k, out, e = 2.0 / (n + 1), [], None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes: Sequence[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI; None until n changes exist."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains, losses = gains + max(d, 0.0), losses + max(-d, 0.0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag, al = (ag * (n - 1) + max(d, 0.0)) / n, (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    return out


def signals_for(rows: Sequence[Sequence[Any]], only_days: set[str] | None = None, off: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """`off` switches single conditions off for the ablation: any of volume, vwap, ema, rsi, gap, liquid.  rows: [day, minute, open, high, low, close, volume] oldest first, several days. Returns the first breakout and the first breakdown signal of each day."""
    if len(rows) < 60:
        return []
    closes = [float(r[5]) for r in rows]
    e9, e20, rs = ema(closes, 9), ema(closes, 20), rsi(closes)
    by_day: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_day[r[0]].append(i)
    days = sorted(by_day)
    daily_vol = {d: sum(float(rows[i][6]) for i in by_day[d]) for d in days}
    out = []
    for di, day in enumerate(days):
        if di == 0 or (only_days and day not in only_days):
            continue
        prev = by_day[days[di - 1]]
        pdh, pdl, pclose = max(float(rows[i][3]) for i in prev), min(float(rows[i][4]) for i in prev), float(rows[prev[-1]][5])
        idx = by_day[day]
        if len(idx) < 6:
            continue
        gap = (float(rows[idx[0]][2]) / pclose - 1) * 100
        window = [daily_vol[d] for d in days[max(0, di - 20):di]]
        liquid = bool(window) and sum(window) / len(window) > MIN_AVG_VOL
        orh, orl = max(float(rows[i][3]) for i in idx[:3]), min(float(rows[i][4]) for i in idx[:3])
        cum_pv = cum_v = 0.0
        done: set[str] = set()
        for n, i in enumerate(idx):
            r = rows[i]
            tp = (float(r[3]) + float(r[4]) + float(r[5])) / 3.0
            cum_pv, cum_v = cum_pv + tp * float(r[6]), cum_v + float(r[6])
            vwap = cum_pv / cum_v if cum_v else float(r[5])
            minute = int(r[1])
            if n < 3 or minute < FIRST_MIN or minute > LAST_MIN or i < 21 or rs[i] is None or (not liquid and "liquid" not in off):
                continue
            avgv = sum(float(rows[k][6]) for k in range(i - 20, i)) / 20.0
            volx = float(r[6]) / avgv if avgv > 0 else 0.0
            c, pc = float(r[5]), float(rows[i - 1][5])
            if volx <= VOL_MULT and "volume" not in off:
                continue
            if "LONG" not in done and (0.0 <= gap <= GAP_MAX or "gap" in off) and (c > vwap or "vwap" in off) and (e9[i] > e20[i] or "ema" in off) and (rs[i] > RSI_LONG or "rsi" in off):
                for kind, lvl in (("PDH", pdh), ("ORH", orh)):
                    if pc <= lvl < c:
                        out.append({"day": day, "side": "LONG", "minute": minute, "level": round(lvl, 2), "level_kind": kind, "close": c, "vol_x": round(volx, 2), "rsi": round(rs[i], 1), "gap_pct": round(gap, 2), "i": i})
                        done.add("LONG")
                        break
            if "SHORT" not in done and (-GAP_MAX <= gap <= 0.0 or "gap" in off) and (c < vwap or "vwap" in off) and (e9[i] < e20[i] or "ema" in off) and (rs[i] < RSI_SHORT or "rsi" in off):
                for kind, lvl in (("PDL", pdl), ("ORL", orl)):
                    if pc >= lvl > c:
                        out.append({"day": day, "side": "SHORT", "minute": minute, "level": round(lvl, 2), "level_kind": kind, "close": c, "vol_x": round(volx, 2), "rsi": round(rs[i], 1), "gap_pct": round(gap, 2), "i": i})
                        done.add("SHORT")
                        break
    return out


# ---------------------------------------------------------------- data ----------------------------------------------------------------------------
def _headers(root: Path) -> dict[str, str]:
    from dotenv import load_dotenv
    sys.path.insert(0, str(root))
    load_dotenv(root / ".env")
    from dhan_auth import resolve_access_token
    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=root, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    return {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}


class Dhan:
    def __init__(self, root: Path = ROOT) -> None:
        import requests
        from core import market_data
        self.upstox = market_data.upstox_only()           # Dhan plan expired (3 Nov 2026): candles come from Upstox
        self.h, self.s, self.last = ({} if self.upstox else _headers(root)), requests.Session(), 0.0

    def candles(self, security_id: str, segment: str, instrument: str, start: str, end: str) -> list[list[float]]:
        import pandas as pd
        if self.upstox:
            from core import market_data
            d = market_data.chart_call("charts/intraday", {"securityId": str(security_id), "exchangeSegment": segment, "instrument": instrument, "interval": "5",
                                                          "fromDate": f"{start} 09:00:00", "toDate": f"{end} 15:30:00"}) or {}
            idx = pd.to_datetime(d.get("timestamp") or [], unit="s", utc=True).tz_convert("Asia/Kolkata")
            return [[t.strftime("%Y-%m-%d"), t.hour * 60 + t.minute, float(o), float(h), float(lo), float(c), float(v)]
                    for t, o, h, lo, c, v in zip(idx, d.get("open", []), d.get("high", []), d.get("low", []), d.get("close", []), d.get("volume", []))]
        for attempt in range(4):
            time.sleep(max(0.0, 0.25 - (time.time() - self.last)))
            self.last = time.time()
            try:
                r = self.s.post("https://api.dhan.co/v2/charts/intraday", headers=self.h, timeout=40, json={"securityId": str(security_id), "exchangeSegment": segment, "instrument": instrument,
                                "interval": "5", "oi": False, "fromDate": f"{start} 09:00:00", "toDate": f"{end} 15:30:00"})
            except Exception:                              # noqa: BLE001 - a dropped connection (Dhan resets them now and then): new session, wait, try again
                import requests
                self.s = requests.Session()
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                return []
            d = r.json()
            idx = pd.to_datetime(d.get("timestamp") or [], unit="s", utc=True).tz_convert("Asia/Kolkata")
            return [[t.strftime("%Y-%m-%d"), t.hour * 60 + t.minute, float(o), float(h), float(lo), float(c), float(v)]
                    for t, o, h, lo, c, v in zip(idx, d.get("open", []), d.get("high", []), d.get("low", []), d.get("close", []), d.get("volume", []))]
        return []


def stock_candles(symbols: Sequence[str], through: str, root: Path = ROOT, dhan: Dhan | None = None) -> dict[str, list[list[float]]]:
    """Cached 5-minute candles per stock from START_DAY; missing stocks or days after the cached ones are fetched."""
    import pandas as pd
    path = CACHE / "stock_5m.json"
    CACHE.mkdir(parents=True, exist_ok=True)
    cache: dict[str, list[list[float]]] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    m = pd.read_csv(root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False, usecols=["EXCH_ID", "SEGMENT", "SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL"])
    eq = m[(m.EXCH_ID == "NSE") & (m.SEGMENT == "E") & (m.INSTRUMENT == "EQUITY")]
    ids = {str(r.UNDERLYING_SYMBOL): int(r.SECURITY_ID) for r in eq.itertuples()}
    dhan = dhan or Dhan(root)
    changed = 0
    for s in symbols:
        have = cache.get(s) or []
        if have and max(r[0] for r in have) >= through or s not in ids:
            continue
        got = dhan.candles(str(ids[s]), "NSE_EQ", "EQUITY", START_DAY, (date.fromisoformat(through) + timedelta(days=1)).isoformat())
        if got:
            cache[s] = got
            changed += 1
            if changed % 20 == 0:
                path.write_text(json.dumps(cache), encoding="utf-8")
                print("stock candles", changed, flush=True)
    path.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def option_for(symbol: str, side: str, day: str, spot: float, root: Path = ROOT) -> tuple[str, float, str] | None:
    """(security id, strike, expiry) of the nearest-the-money option of the nearest expiry on or after `day` in the instrument master (None when the master no longer lists it)."""
    import pandas as pd
    m = _master(root)
    sub = m[(m.UNDERLYING_SYMBOL == symbol) & (m.OPTION_TYPE == ("CE" if side == "LONG" else "PE"))]
    exps = sorted(e for e in sub.exp.unique() if e >= day)
    if not exps:
        return None
    sub = sub[sub.exp == exps[0]]
    row = sub.iloc[(sub.STRIKE_PRICE - spot).abs().argsort().iloc[0]]
    return str(int(row.SECURITY_ID)), float(row.STRIKE_PRICE), exps[0]


_MASTER: dict[str, Any] = {}


def _master(root: Path):
    if "m" not in _MASTER:
        import pandas as pd
        m = pd.read_csv(root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False, usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"])
        m = m[m.INSTRUMENT == "OPTSTK"].copy()
        m["exp"] = m.SM_EXPIRY_DATE.astype(str).str[:10]
        _MASTER["m"] = m
    return _MASTER["m"]


class OptionCache:
    """Option 5-minute candles by (security id, day), kept on disk so a rerun or a variant only fetches what is new."""

    def __init__(self, dhan: Dhan) -> None:
        self.dhan = dhan
        self.path = CACHE / "opt_5m.json"
        self.data: dict[str, list[list[float]]] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.new = 0

    def get(self, sid: str, day: str) -> list[list[float]]:
        key = f"{sid}|{day}"
        if key not in self.data:
            self.data[key] = self.dhan.candles(sid, "NSE_FNO", "OPTSTK", day, (date.fromisoformat(day) + timedelta(days=1)).isoformat())
            self.new += 1
            if self.new % 100 == 0:
                self.save()
                print("option candles fetched", self.new, flush=True)
        return self.data[key]

    def save(self) -> None:
        CACHE.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data), encoding="utf-8")


def follow_option(candles: Sequence[Sequence[float]], day: str, signal_minute: int) -> dict[str, Any]:
    """Replay the live ladder on the option's candles of `day`, entering at the open of the candle after the signal candle."""
    import baseline_replay as br
    bars = sorted((r for r in candles if r[0] == day), key=lambda r: r[1])
    if len(bars) < 5:
        return {}
    m = [r[1] for r in bars]
    k = max((i for i, x in enumerate(m) if x <= signal_minute), default=-1)
    if k < 0:
        return {}
    res = br.simulate(m, [r[2] for r in bars], [r[3] for r in bars], [r[4] for r in bars], [r[5] for r in bars], k)
    return res or {}


# ---------------------------------------------------------------- run -----------------------------------------------------------------------------
def run(days: Sequence[str] | None = None, root: Path = ROOT, symbols: Sequence[str] | None = None) -> Path:
    import rs_leaders  # noqa: F401  (universe comes from the live ranking file)
    universe = sorted(symbols or json.loads((root / "data" / "ticks" / "rs_all.json").read_text(encoding="utf-8")).get("stocks", {}))
    through = max(days) if days else datetime.now(IST).strftime("%Y-%m-%d")
    dhan = Dhan(root)
    candles = stock_candles(universe, through, root, dhan)
    all_days = sorted({r[0] for rows in candles.values() for r in rows})
    want = set(days) if days else {d for d in all_days if d > START_DAY}
    folder = root.joinpath(*FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "signals.csv"
    old = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as h:
            old = [r for r in csv.DictReader(h) if r["day"] not in want]
    new = []
    opts = OptionCache(dhan)
    for sym in universe:
        for sg in signals_for(candles.get(sym) or [], want):
            row = {"day": sg["day"], "symbol": sym, "side": sg["side"], "time": f"{sg['minute'] // 60:02d}:{sg['minute'] % 60:02d}", "level": sg["level"], "level_kind": sg["level_kind"], "close": sg["close"],
                   "vol_x": sg["vol_x"], "rsi": sg["rsi"], "gap_pct": sg["gap_pct"]}
            opt = option_for(sym, sg["side"], sg["day"], sg["close"], root)
            if opt:
                sid, strike, exp = opt
                res = follow_option(opts.get(sid, sg["day"]), sg["day"], sg["minute"])
                if res:
                    row.update({"strike": strike, "option": f"{strike:.0f} {'CE' if sg['side'] == 'LONG' else 'PE'}", "entry": round(res["entry"], 2), "peak_pct": round(res["peak_pct"], 1), "exit": round(res["exit"], 2),
                                "why": res["why"], "gross_pct": round(res["gross_pct"], 1), "net_rs": round(res["net_rs"])})
            new.append(row)
    opts.save()
    rows = sorted(old + new, key=lambda r: (r["day"], r["time"]))
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    out = folder / "review.md"
    out.write_text(review(rows, root), encoding="utf-8")
    try:                                                   # the named variants found by the search (they never stop the plain review above)
        run_variants(want, candles, universe, opts, root)
    except Exception:                                      # noqa: BLE001
        pass
    return out


# Variants found on 5 - 26 Oct (search.md, validated on the option with the live ladder): kept as shadows to be confirmed or dropped on forward days. level names follow breakout_search.mask
# (for a short, "PDH" means the previous-day LOW and RSI N means RSI below 100 - N).
NAMED_VARIANTS = (
    ("LONG_A", 1, dict(level="OR15", vol=3.0, vwap=True, ema=True, rsi=65, gap="off", t0=9 * 60 + 30, body=0.7)),
    ("SHORT_A", -1, dict(level="PDH", vol=1.0, vwap=True, ema=True, rsi=55, gap="0to3", t0=9 * 60 + 30, body=0.0)),
    ("SHORT_C", -1, dict(level="PDH_OR15", vol=2.0, vwap=False, ema=False, rsi=60, gap="off", t0=9 * 60 + 30, body=0.0)),
    ("LEVEL_ONLY_SHORT", -1, dict(level="PDH_OR15", vol=0.0, vwap=False, ema=False, rsi=0, gap="off", t0=9 * 60 + 30, body=0.0)),
)
VARIANT_FIELDS = ["variant", "day", "symbol", "side", "time", "entry", "peak_pct", "exit", "why", "gross_pct", "net_rs"]


def run_variants(want: set[str], candles: Mapping[str, Sequence[Sequence[Any]]], universe: Sequence[str], opts: "OptionCache", root: Path = ROOT) -> Path:
    """Replay each named variant on the days in `want`; signals and outcomes go to data/breakout_rule/variants.csv, a summary to variants.md."""
    import breakout_search as bs
    folder = root.joinpath(*FOLDER)
    path = folder / "variants.csv"
    old: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as h:
            old = [r for r in csv.DictReader(h) if r["day"] not in want]
    D = bs.build({s: candles[s] for s in universe if s in candles})
    syms = list(D["sym_names"])
    day_lists = {s: sorted({r[0] for r in candles[s]}) for s in syms}
    new = []
    for name, side, combo in NAMED_VARIANTS:
        for i in bs.first_per_day(D, bs.mask(D, combo, side)):
            sym = str(syms[int(D["sym"][i])])
            day = day_lists[sym][int(D["day"][i])]
            if day not in want:
                continue
            minute = int(D["minute"][i])
            opt = option_for(sym, "LONG" if side > 0 else "SHORT", day, float(D["close"][i]), root)
            res = follow_option(opts.get(opt[0], day), day, minute) if opt else {}
            if res:
                new.append({"variant": name, "day": day, "symbol": sym, "side": "LONG" if side > 0 else "SHORT", "time": f"{minute // 60:02d}:{minute % 60:02d}", "entry": round(res["entry"], 2),
                            "peak_pct": round(res["peak_pct"], 1), "exit": round(res["exit"], 2), "why": res["why"], "gross_pct": round(res["gross_pct"], 1), "net_rs": round(res["net_rs"])})
    opts.save()
    rows = sorted(old + new, key=lambda r: (r["variant"], r["day"], r["time"]))
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=VARIANT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    lines = ["# Named breakout / breakdown variants (shadow; nothing trades on these)", "", "Option, fills, ladder and Rs 20,000 stake as in review.md.", "",
             "| variant | days | signals | win % | never +1 % | reached +40 % | mean gross | net Rs per trade | total net Rs |", "|---|---|---|---|---|---|---|---|---|"]
    for name, _, _ in NAMED_VARIANTS:
        g = [r for r in rows if r["variant"] == name]
        if g:
            n = len(g)
            lines.append(f"| {name} | {len({r['day'] for r in g})} | {n} | {100 * sum(_f(r['net_rs']) > 0 for r in g) / n:.0f}% | {100 * sum(_f(r['peak_pct']) < 1 for r in g) / n:.0f}% | "
                         f"{100 * sum(_f(r['peak_pct']) >= 40 for r in g) / n:.0f}% | {st.mean(_f(r['gross_pct']) for r in g):+.1f}% | {sum(_f(r['net_rs']) for r in g) / n:+,.0f} | {sum(_f(r['net_rs']) for r in g):+,.0f} |")
    (folder / "variants.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def review(rows: Sequence[Mapping[str, Any]], root: Path = ROOT) -> str:
    done = [r for r in rows if r.get("entry") not in ("", None)]
    days = sorted({r["day"] for r in rows})
    lines = ["# Breakout / breakdown rule (shadow; nothing trades on this)", "", f"Days: {len(days)} ({days[0] if days else '-'} .. {days[-1] if days else '-'}). Signals: {len(rows)}; followed on the option: {len(done)}.", ""]
    if done:
        def block(name: str, g: Sequence[Mapping[str, Any]]) -> str:
            n = len(g)
            return (f"| {name} | {n} | {100 * sum(_f(r['peak_pct']) < 1 for r in g) / n:.0f}% | {100 * sum(_f(r['peak_pct']) >= 40 for r in g) / n:.0f}% | {100 * sum(_f(r['net_rs']) > 0 for r in g) / n:.0f}% | "
                    f"{st.mean(_f(r['gross_pct']) for r in g):+.1f}% | {st.median(_f(r['gross_pct']) for r in g):+.1f}% | {sum(_f(r['net_rs']) for r in g):+,.0f} |")
        lines += ["| set | trades | never reached +1 % | reached +40 % | win % | mean gross | median gross | total net Rs (Rs 20,000 each) |", "|---|---|---|---|---|---|---|---|", block("all signals", done),
                  block("breakout (long)", [r for r in done if r["side"] == "LONG"]), block("breakdown (short)", [r for r in done if r["side"] == "SHORT"])]
        lines += ["", "For comparison, the random-entry control over 89 sessions with the same ladder: win 36 %, mean -8.0 % per trade, about -Rs 1,850 a trade.", "", "By day:", "", "| day | signals | net Rs |", "|---|---|---|"]
        lines += [f"| {d} | {sum(1 for r in done if r['day'] == d)} | {sum(_f(r['net_rs']) for r in done if r['day'] == d):+,.0f} |" for d in days]
    return "\n".join(lines) + "\n"


ABLATIONS = (("all conditions (as given)", frozenset()), ("without volume > 1.5x", frozenset({"volume"})), ("without close vs VWAP", frozenset({"vwap"})), ("without EMA 9 / 20", frozenset({"ema"})),
             ("without RSI", frozenset({"rsi"})), ("without the gap limit", frozenset({"gap"})), ("without the liquidity filter", frozenset({"liquid"})),
             ("price level + volume only", frozenset({"vwap", "ema", "rsi", "gap"})), ("price level only", frozenset({"volume", "vwap", "ema", "rsi", "gap"})))


def ablate(root: Path = ROOT) -> Path:
    """Each condition switched off on its own, then two bare versions; every variant followed on the option with the same ladder. Written to data/breakout_rule/ablation.md."""
    universe = sorted(json.loads((root / "data" / "ticks" / "rs_all.json").read_text(encoding="utf-8")).get("stocks", {}))
    dhan = Dhan(root)
    candles = stock_candles(universe, datetime.now(IST).strftime("%Y-%m-%d"), root, dhan)
    all_days = sorted({r[0] for rows in candles.values() for r in rows})
    want = {d for d in all_days if d > START_DAY}
    opts = OptionCache(dhan)
    lines = ["# Breakout / breakdown rule: one condition off at a time (shadow)", "", f"Days: {len(want)}. Same option, fills, ladder and Rs 20,000 stake as review.md; first signal per stock, side and day.", "",
             "| variant | signals | win % | never +1 % | reached +40 % | mean gross | long: n / mean gross / net Rs | short: n / mean gross / net Rs | total net Rs |", "|---|---|---|---|---|---|---|---|---|"]
    for name, off in ABLATIONS:
        done = []
        for sym in universe:
            for sg in signals_for(candles.get(sym) or [], want, off):
                opt = option_for(sym, sg["side"], sg["day"], sg["close"], root)
                if not opt:
                    continue
                res = follow_option(opts.get(opt[0], sg["day"]), sg["day"], sg["minute"])
                if res:
                    done.append({"side": sg["side"], **res})
        opts.save()
        if not done:
            lines.append(f"| {name} | 0 | | | | | | | |")
            continue
        n = len(done)

        def part(side: str) -> str:
            g = [r for r in done if r["side"] == side]
            return f"{len(g)} / {st.mean(r['gross_pct'] for r in g):+.1f}% / {sum(r['net_rs'] for r in g):+,.0f}" if g else "-"
        lines.append(f"| {name} | {n} | {100 * sum(r['net_rs'] > 0 for r in done) / n:.0f}% | {100 * sum(r['peak_pct'] < 1 for r in done) / n:.0f}% | {100 * sum(r['peak_pct'] >= 40 for r in done) / n:.0f}% | "
                     f"{st.mean(r['gross_pct'] for r in done):+.1f}% | {part('LONG')} | {part('SHORT')} | {sum(r['net_rs'] for r in done):+,.0f} |")
        print(name, n, flush=True)
    out = root.joinpath(*FOLDER) / "ablation.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["ablate"]:
        print(ablate())
        print((ROOT.joinpath(*FOLDER) / "ablation.md").read_text(encoding="utf-8"))
        sys.exit(0)
    print(run(sys.argv[1:] or None))
    print((ROOT.joinpath(*FOLDER) / "review.md").read_text(encoding="utf-8"))
