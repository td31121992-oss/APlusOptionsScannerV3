"""Chirag Rathod strategy - SHADOW scanner. Paper only: it never touches the live scanner, the safety gate or any order.

Rules implemented (from the strategy slides):
  Stock scan, every hour (10:15 .. 14:15), all F&O stocks (no index):
    BULLISH  price above the previous 5 days' highs, above the daily 20 SMA, above the hourly 20 SMA, above the previous 5 hourly
             candles' highs, daily RSI(14) > 60 and hourly RSI(14) > 60
    BEARISH  the mirror (below the lows / SMAs, RSI < 40)
  Market filter: Nifty green -> both sides; Nifty red -> bearish only; Nifty and Bank Nifty disagreeing -> no trades.
  Option: the one-strike-out (next of ATM) CE (bullish) / PE (bearish) of the current month (next month after the 18th).
  Entry: option price within 2% of its own VWAP or its previous-day pivot, with the option VWAP rising (angle), within 60 minutes of the
         signal and not after 13:30.
  Exit: option 5-min close below the pivot (stop), option touches the upper pivot (target), trailing stop 5% below the peak once up 3%,
        loss of Rs 4,000 on the lot, or 15:15.
Everything is simulated from Dhan 5-minute candles and written to data/chirag_shadow/<date>/ (signals.csv, trades.csv, summary.md).
Run:  python chirag_shadow.py            (a service; the supervisor starts it)      python chirag_shadow.py --once [--hour 10]   (one scan now, or replay that hour of today)
"""

from __future__ import annotations

import csv
import json
import os
import socket
import sys
import time
from datetime import date, datetime, time as clock, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
OUT = ROOT / "data" / "chirag_shadow"
LOCK_PORT = 8793
SCAN_HOURS = (10, 11, 12, 13, 14)
NEAR, TRAIL, IN_PROFIT, LOSS_CAP, COST = 0.02, 0.05, 0.03, 4000.0, 0.011
WATCH_MINUTES, LAST_ENTRY = 60, clock(13, 30)
SIGNAL_FIELDS = ["day", "scan_time", "symbol", "side", "price", "rsi_daily", "rsi_hourly", "nifty", "banknifty", "contract", "strike", "expiry", "lot"]
TRADE_FIELDS = ["day", "symbol", "side", "signal_time", "contract", "strike", "expiry", "lot", "status", "entry_time", "entry", "stop", "target", "peak",
                "exit_time", "exit", "reason", "return_pct", "gross", "costs", "net"]


# ----------------------------------------------------------------------------- pure logic (unit tested)
def wilder(closes: np.ndarray, n: int = 14) -> tuple[np.ndarray, np.ndarray]:
    ag, al = np.full(len(closes), np.nan), np.full(len(closes), np.nan)
    if len(closes) <= n:
        return ag, al
    d = np.diff(closes)
    g, lo = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag[n], al[n] = g[:n].mean(), lo[:n].mean()
    for i in range(n, len(d)):
        ag[i + 1] = (ag[i] * (n - 1) + g[i]) / n
        al[i + 1] = (al[i] * (n - 1) + lo[i]) / n
    return ag, al


def rsi_now(avg_gain: float, avg_loss: float, last_close: float, price: float, n: int = 14) -> float:
    if np.isnan(avg_gain) or np.isnan(avg_loss):
        return float("nan")
    d = price - last_close
    g, lo = max(d, 0.0), max(-d, 0.0)
    ag, al = (avg_gain * (n - 1) + g) / n, (avg_loss * (n - 1) + lo) / n
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)


def evaluate_setup(daily: pd.DataFrame, m5: pd.DataFrame, scan_bar: pd.Timestamp) -> dict[str, Any] | None:
    """daily: index = dates, columns h,l,c (completed days). m5: 5-minute bars (index = bar start), columns o,h,l,c,v.
    scan_bar = start time of the last 5-minute bar of an hourly candle (10:10, 11:10, ...). Returns the setup or None."""
    day = scan_bar.normalize()
    m5 = m5[m5.index <= scan_bar]
    if scan_bar not in m5.index:
        return None
    dd = daily[daily.index < day]
    if len(dd) < 21:
        return None
    p = float(m5.c.iloc[-1])
    dc, dh, dl = dd.c.values.astype(float), dd.h.values.astype(float), dd.l.values.astype(float)
    dag, dal = wilder(dc)
    sma_d = (dc[-19:].sum() + p) / 20.0
    p5h, p5l = dh[-5:].max(), dl[-5:].min()
    rsi_d = rsi_now(dag[-1], dal[-1], dc[-1], p)
    work = m5.copy()
    work["day"] = work.index.normalize()
    work["hb"] = ((work.index - work["day"] - pd.Timedelta(hours=9, minutes=15)) // pd.Timedelta(hours=1)).astype(int)
    hb = work.groupby(["day", "hb"]).agg(h=("h", "max"), l=("l", "min"), c=("c", "last")).reset_index()
    if len(hb) < 22:
        return None
    hc, hh, hl = hb.c.values.astype(float), hb.h.values.astype(float), hb.l.values.astype(float)
    j = len(hb) - 1                                                  # the hourly candle that ends at the scan time
    hag, hal = wilder(hc)
    sma_h = (hc[j - 19:j].sum() + p) / 20.0
    ph5h, ph5l = hh[j - 5:j].max(), hl[j - 5:j].min()
    rsi_h = rsi_now(hag[j - 1], hal[j - 1], hc[j - 1], p)
    if np.isnan(rsi_d) or np.isnan(rsi_h):
        return None
    side = None
    if p > p5h and p > sma_d and p > sma_h and p > ph5h and rsi_d > 60 and rsi_h > 60:
        side = "BULL"
    elif p < p5l and p < sma_d and p < sma_h and p < ph5l and rsi_d < 40 and rsi_h < 40:
        side = "BEAR"
    if side is None:
        return None
    return {"side": side, "price": p, "rsi_daily": round(rsi_d, 1), "rsi_hourly": round(rsi_h, 1)}


def market_allows(side: str, nifty_green: bool | None, bank_green: bool | None) -> bool:
    """Nifty green -> both sides; Nifty red -> bearish only; Nifty and Bank Nifty on opposite sides -> nothing."""
    if nifty_green is None or bank_green is None or nifty_green != bank_green:
        return False
    return True if nifty_green else side == "BEAR"


def pivots(prev_day: pd.DataFrame) -> dict[str, float]:
    high, low, close = float(prev_day.h.max()), float(prev_day.l.min()), float(prev_day.c.iloc[-1])
    p = (high + low + close) / 3.0
    return {"P": p, "R1": 2 * p - low, "R2": p + (high - low), "R3": high + 2 * (p - low), "S1": 2 * p - high}


def replay_option(candles: pd.DataFrame, day: pd.Timestamp, signal_end: pd.Timestamp, lot: int) -> dict[str, Any]:
    """Replays the entry/exit rules on the option's candles (all days up to now). Idempotent: call it again with more candles."""
    prev = candles[candles.index.normalize() < day]
    g = candles[candles.index.normalize() == day]
    g = g[g.c > 0]
    if prev.empty or len(g) < 3:
        return {"status": "NO_DATA"}
    prev = prev[prev.index.normalize() == prev.index.normalize().max()]
    lv = pivots(prev)
    tp = (g.h + g.l + g.c) / 3.0
    vol = g.v.cumsum().replace(0, np.nan)
    vwap = (tp * g.v).cumsum() / vol
    idx = list(g.index)
    start = max(signal_end, day + pd.Timedelta(hours=10, minutes=15))
    entry_i = None
    for i, ts in enumerate(idx):
        if ts < start:
            continue
        if ts > start + pd.Timedelta(minutes=WATCH_MINUTES) or ts.time() > LAST_ENTRY:
            return {"status": "NO_ENTRY", **{k: round(v, 2) for k, v in lv.items()}}
        v = vwap.iloc[i]
        if np.isnan(v):
            continue
        c = float(g.c.iloc[i])
        near = abs(c / v - 1) <= NEAR or abs(c / lv["P"] - 1) <= NEAR
        angle = v > vwap.iloc[max(0, i - 3)]
        if near and angle:
            entry_i = i
            break
    if entry_i is None:
        return {"status": "WATCHING", **{k: round(v, 2) for k, v in lv.items()}}
    e = float(g.c.iloc[entry_i])
    cap_px = e - LOSS_CAP / lot
    sl = lv["P"] if e >= lv["P"] * 1.01 else lv["S1"]
    if sl >= e * 0.995:
        sl = None
    tgt = next((lv[k] for k in ("R1", "R2", "R3") if lv[k] > e * 1.02), None)
    peak, reason, px, exit_ts = e, None, None, None
    for j in range(entry_i + 1, len(idx)):
        ts = idx[j]
        o, h, lo, c = (float(g.o.iloc[j]), float(g.h.iloc[j]), float(g.l.iloc[j]), float(g.c.iloc[j]))
        if ts.time() >= clock(15, 15):
            px, reason, exit_ts = o, "EOD", ts
            break
        if lo <= cap_px:
            px, reason, exit_ts = (min(o, cap_px) if o < cap_px else cap_px), "LOSS_CAP", ts
            break
        if peak >= e * (1 + IN_PROFIT) and lo <= peak * (1 - TRAIL):
            px, reason, exit_ts = min(o, peak * (1 - TRAIL)), "TRAIL5", ts
            break
        if sl is not None and c < sl:
            px, reason, exit_ts = c, "PIVOT_SL", ts
            break
        if tgt is not None and h >= tgt:
            px, reason, exit_ts = (max(tgt, o) if o > tgt else tgt), "PIVOT_TARGET", ts
            break
        peak = max(peak, h)
    status = "CLOSED" if reason else "OPEN"
    last = float(g.c.iloc[-1])
    mark = px if reason else last
    gross = (mark - e) * lot
    return {"status": status, "entry_time": idx[entry_i].strftime("%H:%M"), "entry": round(e, 2), "stop": None if sl is None else round(sl, 2),
            "target": None if tgt is None else round(tgt, 2), "peak": round(peak, 2), "exit_time": exit_ts.strftime("%H:%M") if exit_ts is not None else "",
            "exit": round(mark, 2) if reason else "", "reason": reason or "", "return_pct": round((mark / e - 1) * 100, 2), "gross": round(gross),
            "costs": round(COST * e * lot), "net": round(gross - COST * e * lot), "last_price": round(last, 2)}


def pick_option(master: pd.DataFrame, symbol: str, side: str, spot: float, today: date) -> dict[str, Any] | None:
    """Next-of-ATM option of the current month (the next month once the 18th has passed). master: OPTSTK rows with exp, STRIKE_PRICE, ..."""
    kind = "CE" if side == "BULL" else "PE"
    sub = master[(master.UNDERLYING_SYMBOL == symbol) & (master.OPTION_TYPE == kind)]
    expiries = sorted(e for e in sub.exp.unique() if e >= today.isoformat())
    if not expiries:
        return None
    expiry = expiries[1] if today.day > 18 and len(expiries) > 1 else expiries[0]
    sub = sub[sub.exp == expiry]
    strikes = sorted(sub.STRIKE_PRICE.unique())
    if not strikes:
        return None
    atm = min(strikes, key=lambda k: abs(k - spot))
    i = strikes.index(atm)
    strike = strikes[min(i + 1, len(strikes) - 1)] if kind == "CE" else strikes[max(i - 1, 0)]
    row = sub[sub.STRIKE_PRICE == strike].iloc[0]
    return {"sid": str(int(row.SECURITY_ID)), "strike": float(strike), "expiry": expiry, "lot": int(row.LOT_SIZE), "kind": kind,
            "contract": f"{symbol}-{expiry}-{strike:g}-{kind}"}


# ----------------------------------------------------------------------------- Dhan access and the service loop
class Dhan:
    def __init__(self) -> None:
        import requests
        from dotenv import load_dotenv

        sys.path.insert(0, str(ROOT))
        load_dotenv(ROOT / ".env")
        from dhan_auth import resolve_access_token

        self.requests, self.resolve = requests, resolve_access_token
        self.session = requests.Session()
        self.last = 0.0
        self._cached: tuple[float, dict[str, str]] | None = None

    def _headers(self) -> dict[str, str]:
        if self._cached and time.time() - self._cached[0] < 600:           # validating the token costs ~2 s: reuse it for 10 minutes
            return self._cached[1]
        cid = os.getenv("DHAN_CLIENT_ID", "").strip()
        token = self.resolve(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
        headers = {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}
        self._cached = (time.time(), headers)
        return headers

    def post(self, url: str, body: dict[str, Any]) -> dict[str, Any] | None:
        for attempt in range(3):
            time.sleep(max(0.0, 0.6 - (time.time() - self.last)))
            self.last = time.time()
            try:
                r = self.session.post(url, headers=self._headers(), json=body, timeout=40)
            except Exception:                                      # noqa: BLE001
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            return r.json() if r.status_code == 200 else None
        return None

    @staticmethod
    def frame(d: dict[str, Any] | None, daily: bool = False) -> pd.DataFrame | None:
        if not d or not d.get("timestamp"):
            return None
        t = pd.to_datetime(d["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
        df = pd.DataFrame({"o": d["open"], "h": d["high"], "l": d["low"], "c": d["close"], "v": d["volume"]}, index=t)
        return df.set_index(df.index.normalize()) if daily else df

    def intraday(self, sid: int | str, segment: str, instrument: str, start: str, end: str) -> pd.DataFrame | None:
        return self.frame(self.post("https://api.dhan.co/v2/charts/intraday", {
            "securityId": str(sid), "exchangeSegment": segment, "instrument": instrument, "interval": "5", "oi": False,
            "fromDate": f"{start} 09:15:00", "toDate": f"{end} 15:30:00"}))

    def daily(self, sid: int | str) -> pd.DataFrame | None:
        start = (date.today() - timedelta(days=170)).isoformat()
        return self.frame(self.post("https://api.dhan.co/v2/charts/historical", {
            "securityId": str(sid), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "expiryCode": 0, "oi": False,
            "fromDate": start, "toDate": (date.today() + timedelta(days=1)).isoformat()}), daily=True)


def _append(path: Path, fields: list[str], rows: list[dict[str, Any]], rewrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if rewrite or not path.exists() else "a"
    with path.open(mode, newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if mode == "w":
            w.writeheader()
        w.writerows(rows)


def write_summary(folder: Path, day: str, trades: list[dict[str, Any]], signals: int) -> None:
    done = [t for t in trades if t.get("status") in ("OPEN", "CLOSED")]
    net = sum(float(t.get("net") or 0) for t in done)
    wins = sum(1 for t in done if float(t.get("net") or 0) > 0)
    lines = [f"# Chirag Rathod shadow - {day}", "", f"{signals} signals, {len(done)} simulated trades "
             f"({sum(1 for t in done if t['status'] == 'OPEN')} still open at the last mark), winners {wins}, **net Rs {net:+,.0f}** (after about 1.1% costs).", "",
             "| Symbol | Side | Contract | Entry | Exit | Reason | Return % | Net Rs |", "|---|---|---|---|---|---|---|---|"]
    for t in done:
        lines.append(f"| {t['symbol']} | {t['side']} | {t['contract']} | {t['entry_time']} @ {t['entry']} | {t.get('exit_time', '')} @ {t.get('exit', '')} | "
                     f"{t.get('reason') or t['status']} | {t.get('return_pct', '')} | {t.get('net', '')} |")
    lines += ["", "Simulated from 5-minute candles with no slippage; paper only."]
    (folder / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


class Shadow:
    def __init__(self, dhan: Dhan, root: Path = ROOT) -> None:
        import pandas as pd_

        self.dhan, self.root = dhan, root
        self.universe: dict[str, int] = {}
        self.master = None
        self.daily_cache: dict[str, pd.DataFrame] = {}
        self.history_cache: dict[str, pd.DataFrame] = {}
        self.state: dict[str, Any] = {"day": "", "signals": [], "scans_done": []}
        self._pd = pd_

    def _folder(self, day: str) -> Path:
        return self.root / "data" / "chirag_shadow" / day

    def _load_state(self, day: str) -> None:
        if self.state.get("day") == day:
            return
        path = self._folder(day) / "state.json"
        try:
            self.state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.state = {"day": day, "signals": [], "scans_done": []}
        self.daily_cache, self.history_cache = {}, {}

    def _save_state(self) -> None:
        folder = self._folder(self.state["day"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "state.json").write_text(json.dumps(self.state), encoding="utf-8")

    def _prepare(self) -> None:
        if self.universe:
            return
        sys.path.insert(0, str(self.root))
        from order_book_recorder import _universe

        self.universe = _universe()
        m = pd.read_csv(self.root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                        usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE", "LOT_SIZE"])
        m = m[m.INSTRUMENT == "OPTSTK"].copy()
        m["exp"] = m.SM_EXPIRY_DATE.astype(str).str[:10]
        self.master = m

    def _index_green(self, name: str, sid: int, today: str, scan_bar: pd.Timestamp) -> bool | None:
        start = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
        df = self.dhan.intraday(sid, "IDX_I", "INDEX", start, (date.fromisoformat(today) + timedelta(days=1)).isoformat())
        if df is None:
            return None
        prev = df[df.index.normalize() < pd.Timestamp(today)]
        now = df[(df.index.normalize() == pd.Timestamp(today)) & (df.index <= scan_bar)]
        if prev.empty or now.empty:
            return None
        return bool(now.c.iloc[-1] > prev.c.iloc[-1])

    def scan(self, now: datetime, hour: int) -> int:
        """One hourly scan of all stocks. Returns the number of new signals."""
        day = now.date().isoformat()
        self._load_state(day)
        self._prepare()
        scan_bar = pd.Timestamp(f"{day} {hour:02d}:10:00")
        nifty = self._index_green("NIFTY", 13, day, scan_bar)
        bank = self._index_green("BANKNIFTY", 25, day, scan_bar)
        start = (date.fromisoformat(day) - timedelta(days=30)).isoformat()
        end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        seen = {(s["symbol"], s["side"]) for s in self.state["signals"]}
        new = 0
        for symbol, sid in sorted(self.universe.items()):
            try:
                if symbol not in self.daily_cache:
                    self.daily_cache[symbol] = self.dhan.daily(sid)
                daily = self.daily_cache[symbol]
                m5 = self.dhan.intraday(sid, "NSE_EQ", "EQUITY", start, end)
                if daily is None or m5 is None:
                    continue
                setup = evaluate_setup(daily, m5, scan_bar)
                if not setup or (symbol, setup["side"]) in seen or not market_allows(setup["side"], nifty, bank):
                    continue
                opt = pick_option(self.master, symbol, setup["side"], setup["price"], date.fromisoformat(day))
                if opt is None:
                    continue
                sig = {"day": day, "scan_time": f"{hour:02d}:15", "symbol": symbol, "side": setup["side"], "price": round(setup["price"], 2),
                       "rsi_daily": setup["rsi_daily"], "rsi_hourly": setup["rsi_hourly"], "nifty": "green" if nifty else "red",
                       "banknifty": "green" if bank else "red", "contract": opt["contract"], "strike": opt["strike"], "expiry": opt["expiry"],
                       "lot": opt["lot"], "sid": opt["sid"]}
                self.state["signals"].append(sig)
                seen.add((symbol, setup["side"]))
                _append(self._folder(day) / "signals.csv", SIGNAL_FIELDS, [sig])
                new += 1
            except Exception:                                      # noqa: BLE001 - one stock must never stop the scan
                continue
        self.state["scans_done"].append(hour)
        self._save_state()
        return new

    def poll(self, now: datetime) -> None:
        """Re-simulate every signal's option from its candles and rewrite trades.csv / summary.md."""
        day = now.date().isoformat()
        self._load_state(day)
        rows = []
        for sig in self.state["signals"]:
            try:
                start = (date.fromisoformat(day) - timedelta(days=6)).isoformat()
                candles = self.dhan.intraday(sig["sid"], "NSE_FNO", "OPTSTK", start, (date.fromisoformat(day) + timedelta(days=1)).isoformat())
                hh, mm = map(int, sig["scan_time"].split(":"))
                res = replay_option(candles, pd.Timestamp(day), pd.Timestamp(f"{day} {hh:02d}:{mm:02d}:00"), int(sig["lot"])) if candles is not None else {"status": "NO_DATA"}
            except Exception:                                      # noqa: BLE001
                res = {"status": "NO_DATA"}
            rows.append({"day": day, "symbol": sig["symbol"], "side": sig["side"], "signal_time": sig["scan_time"], "contract": sig["contract"],
                         "strike": sig["strike"], "expiry": sig["expiry"], "lot": sig["lot"], **res})
        folder = self._folder(day)
        _append(folder / "trades.csv", TRADE_FIELDS, rows, rewrite=True)
        write_summary(folder, day, rows, len(self.state["signals"]))


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and clock(10, 15) <= now.time() <= clock(15, 40)


def main() -> int:
    once = "--once" in sys.argv
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return 0                                                   # already running
    shadow = Shadow(Dhan())
    while True:
        started = time.time()
        now = datetime.now(IST).replace(tzinfo=None)
        try:
            if once:
                hour = max(h for h in SCAN_HOURS if h <= now.hour) if now.hour >= 10 else 10
                if "--hour" in sys.argv:                           # replay an earlier scan hour of today (testing)
                    hour = int(sys.argv[sys.argv.index("--hour") + 1])
                print("new signals:", shadow.scan(now, hour))
                shadow.poll(now)
                return 0
            if in_session(now):
                shadow._load_state(now.date().isoformat())
                for hour in SCAN_HOURS:
                    if hour not in shadow.state["scans_done"] and now.time() >= clock(hour, 16):
                        shadow.scan(now, hour)
                if now.minute % 5 == 1 or not shadow.state.get("polled"):
                    shadow.poll(now)
                    shadow.state["polled"] = True
        except Exception:                                          # noqa: BLE001 - the service must never crash
            pass
        time.sleep(max(5.0, 60 - (time.time() - started)))


if __name__ == "__main__":
    raise SystemExit(main())
