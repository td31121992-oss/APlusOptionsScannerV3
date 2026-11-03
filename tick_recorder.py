"""Dhan live tick recorder for a few stocks (DATA ONLY - never touches the scanner or any trade).

Why: footprint / order-flow charts need every trade tagged as buyer- or seller-initiated. The order-book recorder keeps one snapshot a minute, which is far too sparse. This
subscribes to Dhan's live market feed (Full mode: last price and quantity, volume, total buy / sell quantity, best bid / ask and the 5-level book) for 10 liquid stocks and
writes every packet, so delta, cumulative delta and imbalance can be rebuilt per candle afterwards (see footprint_lite.py).

    data/ticks/<day>/<SYMBOL>.csv.gz     columns: ts (receive time IST, ms), sym, ltp, ltq, ltt, vol, tbq, tsq, bid, bq, ask, aq, bsum5, asum5, tq, side
        tq    quantity traded since the previous packet (change in day volume), blank when nothing traded
        side  B = buyer-initiated (price at or above the previous best ask), S = seller-initiated (at or below the previous best bid),
              otherwise the tick rule (price up = B, down = S, flat = the last side); blank when nothing traded
    data/ticks/health.json               packets, last tick time, restarts (updated every 30 seconds)

It is an approximation: a feed packet can cover several trades, and the buy/sell tag is inferred. Symbols: every F&O stock by default (APLUS_TICK_SYMBOLS=ALL);
APLUS_TICK_SYMBOLS can instead be a comma list (the old ten are DEFAULT_SYMBOLS).
Runs 09:05-15:32 IST on trading days (the scheduled task APlus_Tick_Recorder starts it); it reconnects if the feed goes quiet for a minute.

    python tick_recorder.py               record until 15:32
    python tick_recorder.py --selftest 20 connect for 20 seconds, print what arrived, write nothing permanent
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_SYMBOLS = ("INFY", "TCS", "TECHM", "WIPRO", "KPITTECH", "HDFCBANK", "ICICIBANK", "SBIN", "RELIANCE", "BHARTIARTL")
FIELDS = ["ts", "sym", "ltp", "ltq", "ltt", "vol", "tbq", "tsq", "bid", "bq", "ask", "aq", "bsum5", "asum5", "tq", "side"]
START, END = (9, 5), (15, 32)
STALE_SECONDS = 60


def resolve_symbols(setting: str, universe: dict[str, Any]) -> tuple[str, ...]:
    """ALL (or empty) -> every F&O stock in the universe; otherwise the listed symbols that exist in it."""
    setting = (setting or "ALL").strip()
    if setting.upper() == "ALL":
        return tuple(sorted(universe))
    return tuple(s for s in (x.strip().upper() for x in setting.split(",")) if s in universe)


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def classify(prev: dict[str, Any] | None, ltp: float, vol: float) -> tuple[str, int]:
    """(side, traded quantity) for a packet, from the previous packet's state. ('', 0) when no volume traded since."""
    if prev is None or vol <= prev["vol"]:
        return "", 0
    qty = int(vol - prev["vol"])
    if prev["ask"] > 0 and ltp >= prev["ask"]:
        side = "B"
    elif prev["bid"] > 0 and ltp <= prev["bid"]:
        side = "S"
    elif ltp > prev["ltp"]:
        side = "B"
    elif ltp < prev["ltp"]:
        side = "S"
    else:
        side = prev.get("side") or ""
    return side, qty


def packet_row(data: dict[str, Any], sym: str, prev: dict[str, Any] | None, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """One CSV row and the new 'previous' state from a parsed Full packet (the dict the dhanhq library produces)."""
    depth = data.get("depth") or []
    top = depth[0] if depth else {}
    ltp, vol = _f(data.get("LTP")), _f(data.get("volume"))
    side, qty = classify(prev, ltp, vol)
    bid, ask = _f(top.get("bid_price")), _f(top.get("ask_price"))
    row = {"ts": now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}", "sym": sym, "ltp": f"{ltp:.2f}", "ltq": int(_f(data.get("LTQ"))), "ltt": data.get("LTT", ""),
           "vol": int(vol), "tbq": int(_f(data.get("total_buy_quantity"))), "tsq": int(_f(data.get("total_sell_quantity"))), "bid": f"{bid:.2f}", "bq": int(_f(top.get("bid_quantity"))),
           "ask": f"{ask:.2f}", "aq": int(_f(top.get("ask_quantity"))), "bsum5": int(sum(_f(d.get("bid_quantity")) for d in depth)),
           "asum5": int(sum(_f(d.get("ask_quantity")) for d in depth)), "tq": qty or "", "side": side}
    state = {"vol": vol, "ltp": ltp, "bid": bid, "ask": ask, "side": side or (prev or {}).get("side", "")}
    return row, state


class TickWriter:
    def __init__(self, root: Path, day: str) -> None:
        self.folder = root / "data" / "ticks" / day
        self.folder.mkdir(parents=True, exist_ok=True)
        try:                                       # a recorder that died without closing its files leaves cut-off gzip members that block reading everything written after them: repair first
            import tick_gz

            for p in self.folder.glob("*.csv.gz"):
                tick_gz.repair(p)
        except Exception:                          # noqa: BLE001 - repairing is best effort
            pass
        self._files: dict[str, Any] = {}
        self._last_flush = time.monotonic()
        self._lock = threading.Lock()

    def write(self, row: dict[str, Any]) -> None:
        with self._lock:
            f = self._files.get(row["sym"])
            if f is None:
                path = self.folder / f"{row['sym']}.csv.gz"
                new = not path.exists()
                f = gzip.open(path, "at", encoding="utf-8", newline="")
                if new:
                    f.write(",".join(FIELDS) + "\n")
                self._files[row["sym"]] = f
            f.write(",".join(str(row.get(k, "")) for k in FIELDS) + "\n")
            if time.monotonic() - self._last_flush > 5:
                for h in self._files.values():
                    h.flush()
                self._last_flush = time.monotonic()

    def close(self) -> None:
        with self._lock:
            for h in self._files.values():
                try:
                    h.close()
                except Exception:                          # noqa: BLE001
                    pass
            self._files.clear()


def rs_leaders_ids() -> list[int]:
    try:
        import rs_leaders

        return rs_leaders.INDEX_IDS
    except Exception:                          # noqa: BLE001
        return []


class Recorder:
    def __init__(self, root: Path, symbols: tuple[str, ...], ids: dict[str, str], day: str | None = None) -> None:
        self.root, self.symbols, self.ids = root, symbols, ids
        self.sym_by_id = {str(v): k for k, v in ids.items()}
        self.day = day or date.today().isoformat()
        self.writer = TickWriter(root, self.day)
        self.prev: dict[str, dict[str, Any]] = {}
        self.packets = 0
        self.rows = 0
        self.restarts = 0
        self.last_packet = 0.0
        self.last_error = ""
        self.detector = None
        self.events = None
        try:                                       # shadow burst detector (tick_detector.py): records events, never trades
            import tick_detector

            if tick_detector.enabled():
                self.detector = tick_detector.TickDetector()
                self.events = tick_detector.EventLog(root, self.day)
        except Exception as exc:                   # noqa: BLE001 - recording must never depend on it
            self.last_error = f"tick_detector off: {type(exc).__name__}: {exc}"
        self.big = None
        try:                                       # live big-print totals for the Big Players page (big_prints.py)
            import big_prints

            self.big = big_prints.BigPrintTracker()
        except Exception as exc:                   # noqa: BLE001
            self.last_error = f"big_prints off: {type(exc).__name__}: {exc}"
        self.rs = None
        self.idxlog = None
        self.mb = None
        self.delta = None
        self.amt = None
        self.story = None
        try:                                       # what every 5-minute candle says and the story of the last few (candle_story.py)
            import candle_story

            self.story = candle_story.StoryTracker(candle_story.load_levels(root))
        except Exception as exc:                   # noqa: BLE001
            self.last_error = f"candle_story off: {type(exc).__name__}: {exc}"
        try:                                       # auction-market-theory levels and CVD divergence (amt_profile.py)
            import amt_profile

            self.amt = amt_profile.AMTTracker()
        except Exception as exc:                   # noqa: BLE001
            self.last_error = f"amt_profile off: {type(exc).__name__}: {exc}"
        try:                                       # cumulative buy-minus-sell volume and its sign flips (delta_flow.py)
            import delta_flow

            self.delta = delta_flow.DeltaTracker()
        except Exception as exc:                   # noqa: BLE001
            self.last_error = f"delta_flow off: {type(exc).__name__}: {exc}"
        try:                                       # 1-minute closes -> live chart features for the shadow ML score (ml_shadow.py)
            import ml_shadow

            self.mb = ml_shadow.MinuteBars()
        except Exception as exc:                   # noqa: BLE001
            self.last_error = f"ml_shadow off: {type(exc).__name__}: {exc}"
        try:                                       # live relative-strength ranking for the Market Leaders page and the rs_ tags (rs_leaders.py)
            import money_flow
            import rs_leaders

            ref = rs_leaders.load_reference(root, self.day)
            if ref:
                self.rs = rs_leaders.RSTracker(ref, money_flow._sector_map(root))
                self.idxlog = rs_leaders.IndexLog(root, self.day)
        except Exception as exc:                   # noqa: BLE001
            self.last_error = f"rs_leaders off: {type(exc).__name__}: {exc}"

    def on_message(self, feed: Any, data: Any) -> None:
        if isinstance(data, dict) and self.rs is not None and data.get("type") in ("Ticker Data", "Previous Close") and str(data.get("exchange_segment")) == "0" and str(data.get("security_id")).isdigit() \
                and int(data["security_id"]) in rs_leaders_ids():
            try:                                   # NIFTY 50 and the sector indices (segment 0: a stock may share an id on the equity segment) for the leaders' comparisons
                sid, now = int(data["security_id"]), datetime.now(IST)
                ts = now.strftime("%H:%M:%S.%f")[:-3]
                if data["type"] == "Ticker Data":
                    self.rs.set_index(ltp=float(data.get("LTP") or 0), sid=sid)
                    self.idxlog.write(sid, "L", float(data.get("LTP") or 0), ts, now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6)
                else:
                    self.rs.set_index(prev=float(data.get("prev_close") or 0), sid=sid)
                    self.idxlog.write(sid, "P", float(data.get("prev_close") or 0), ts, 0.0)
            except Exception as exc:               # noqa: BLE001
                self.last_error = f"rs_leaders index: {type(exc).__name__}: {exc}"
            return
        if not isinstance(data, dict) or data.get("type") != "Full Data":
            return
        sym = self.sym_by_id.get(str(data.get("security_id")))
        if not sym:
            return
        self.packets += 1
        self.last_packet = time.monotonic()
        row, state = packet_row(data, sym, self.prev.get(sym), datetime.now(IST))
        self.prev[sym] = state
        self.writer.write(row)
        self.rows += 1
        if self.detector is not None:
            try:
                ev = self.detector.update(sym, row["ts"], float(row["ltp"]), float(row["tq"] or 0), row["side"])
                if ev:
                    self.events.write(ev)
            except Exception as exc:               # noqa: BLE001 - a detector error must not stop the recording
                self.last_error = f"tick_detector: {type(exc).__name__}: {exc}"
        if self.big is not None:
            try:
                self.big.update(sym, row["ts"], float(row["ltp"]), float(row["tq"] or 0), row["side"])
                h, m, s = row["ts"].split(":")
                self.big.maybe_write(self.root, self.day, int(h) * 3600 + int(m) * 60 + float(s))
            except Exception as exc:               # noqa: BLE001 - must not stop the recording
                self.last_error = f"big_prints: {type(exc).__name__}: {exc}"
        if self.rs is not None:
            try:
                self.rs.update(sym, row["ts"], float(row["ltp"]), float(row["vol"] or 0), float(data.get("avg_price") or 0), float(row.get("bid") or 0), float(row.get("ask") or 0))
                self.rs.maybe_write(self.root, self.day)
            except Exception as exc:               # noqa: BLE001 - must not stop the recording
                self.last_error = f"rs_leaders: {type(exc).__name__}: {exc}"
        if self.story is not None:
            try:
                h, m, s = row["ts"].split(":")
                t_s = int(h) * 3600 + int(m) * 60 + float(s)
                self.story.maybe_write(self.root, self.day, t_s, time.monotonic(), self.story.update(sym, t_s, float(row["ltp"]), float(row["tq"] or 0), row["side"]))
            except Exception as exc:               # noqa: BLE001 - must not stop the recording
                self.last_error = f"candle_story: {type(exc).__name__}: {exc}"
        if self.amt is not None:
            try:
                h, m, s = row["ts"].split(":")
                t_s = int(h) * 3600 + int(m) * 60 + float(s)
                self.amt.maybe_write(self.root, self.day, t_s, time.monotonic(), self.amt.update(sym, t_s, float(row["ltp"]), float(row["tq"] or 0), row["side"]))
            except Exception as exc:               # noqa: BLE001 - must not stop the recording
                self.last_error = f"amt_profile: {type(exc).__name__}: {exc}"
        if self.delta is not None:
            try:
                h, m, s = row["ts"].split(":")
                t_s = int(h) * 3600 + int(m) * 60 + float(s)
                ev = self.delta.update(sym, t_s, float(row["ltp"]), float(row["tq"] or 0), row["side"])
                self.delta.maybe_write(self.root, self.day, t_s, time.monotonic(), [ev] if ev else [])
            except Exception as exc:               # noqa: BLE001 - must not stop the recording
                self.last_error = f"delta_flow: {type(exc).__name__}: {exc}"
        if self.mb is not None:
            try:
                h, m, s = row["ts"].split(":")
                t_s = int(h) * 3600 + int(m) * 60 + float(s)
                self.mb.update(sym, t_s, float(row["ltp"]))
                self.mb.maybe_write(self.root, self.day, t_s, time.monotonic())
            except Exception as exc:               # noqa: BLE001 - must not stop the recording
                self.last_error = f"ml_shadow: {type(exc).__name__}: {exc}"

    def on_error(self, feed: Any, error: Exception) -> None:
        self.last_error = f"{type(error).__name__}: {error}"

    def health(self) -> dict[str, Any]:
        return {"day": self.day, "updated": datetime.now(IST).isoformat(timespec="seconds"), "symbols": list(self.symbols), "packets": self.packets, "rows": self.rows,
                "restarts": self.restarts, "events": self.events.count if self.events else 0, "seconds_since_packet": None if not self.last_packet else round(time.monotonic() - self.last_packet, 1), "last_error": self.last_error}

    def write_health(self) -> None:
        try:
            p = self.root / "data" / "ticks" / "health.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.health()), encoding="utf-8")
        except OSError:
            pass


def _credentials(root: Path) -> tuple[str, str]:
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    sys.path.insert(0, str(root))
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    return cid, resolve_access_token(project_root=root, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())


def _log_crash(root: Path, where: str) -> None:
    """Append the current traceback to data/ticks/recorder_error.log (the scheduled task keeps no console output)."""
    import traceback

    try:
        with (root / "data" / "ticks" / "recorder_error.log").open("a", encoding="utf-8") as h:
            h.write(f"--- {datetime.now(IST).isoformat(timespec='seconds')} in {where}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def _feed_credentials(root: Path) -> tuple[str, str]:
    """Dhan client id and token, or blanks when the data provider is Upstox (its feed uses the Upstox token, so no Dhan token is resolved)."""
    sys.path.insert(0, str(root))
    import upstox_feed

    return ("", "") if upstox_feed.feed_provider() == "UPSTOX" else _credentials(root)


def _start_upstox_feed(rec: Recorder) -> Any:
    from upstox_feed import UpstoxMarketFeed

    instruments = [("NSE_EQ", str(rec.ids[s]), "full") for s in rec.symbols]
    instruments += [("IDX_I", str(i), "ticker") for i in rs_leaders_ids()]          # NIFTY 50 and the sector indices, as on Dhan
    feed = UpstoxMarketFeed(instruments, rec.on_message, rec.on_error)
    feed.start()
    return feed


def _start_feed(rec: Recorder, cid: str, token: str) -> Any:
    import upstox_feed

    if upstox_feed.feed_provider() == "UPSTOX":
        try:
            return _start_upstox_feed(rec)
        except Exception as exc:                           # noqa: BLE001 - no Upstox token / mapping problem: record from Dhan instead of not at all
            rec.last_error = f"Upstox feed unavailable, using Dhan: {type(exc).__name__}: {exc}"
            cid, token = _credentials(ROOT)
    from dhanhq import DhanContext, MarketFeed

    instruments = [(MarketFeed.NSE, str(rec.ids[s]), MarketFeed.Full) for s in rec.symbols]
    instruments += [(MarketFeed.IDX, str(i), MarketFeed.Ticker) for i in rs_leaders_ids()]      # NIFTY 50 and the sector indices for the relative-strength comparisons (rs_leaders.py)
    feed = MarketFeed(DhanContext(cid, token), instruments, "v2", on_message=rec.on_message, on_error=rec.on_error)
    feed.start()
    return feed


def run(root: Path = ROOT, selftest_seconds: float = 0.0) -> int:
    sys.path.insert(0, str(root))
    from order_book_recorder import _universe

    uni = _universe()
    symbols = resolve_symbols(os.getenv("APLUS_TICK_SYMBOLS", "ALL"), uni)
    ids = {s: str(uni[s]) for s in symbols if s in uni}
    if not ids:
        print("no known symbols")
        return 2
    if selftest_seconds:
        import tempfile

        root_out = Path(tempfile.mkdtemp(prefix="ticks_selftest_"))
    else:
        root_out = root
    rec = Recorder(root_out, tuple(ids), ids)
    cid, token = _feed_credentials(root)
    end = datetime.now(IST).replace(hour=END[0], minute=END[1], second=0, microsecond=0)
    feed = _start_feed(rec, cid, token)
    t0 = time.monotonic()
    last_health = 0.0
    try:
        while True:
            time.sleep(1.0)
            now = time.monotonic()
            if selftest_seconds and now - t0 >= selftest_seconds:
                break
            if not selftest_seconds and datetime.now(IST) >= end:
                break
            if now - last_health > 30:
                rec.write_health()
                last_health = now
            quiet = now - (rec.last_packet or t0)
            if not selftest_seconds and quiet > STALE_SECONDS and datetime.now(IST).hour * 60 + datetime.now(IST).minute >= START[0] * 60 + START[1]:
                rec.restarts += 1                          # the feed went quiet during the session: reconnect
                try:
                    feed.close_connection()
                except Exception:                          # noqa: BLE001
                    pass
                time.sleep(2)
                try:
                    cid, token = _feed_credentials(root)
                    feed = _start_feed(rec, cid, token)
                    rec.last_packet = time.monotonic()
                except Exception as exc:                   # noqa: BLE001 - a failed reconnect must not end the recording: try again in about 10 seconds
                    _log_crash(root, "reconnect")
                    rec.last_error = f"reconnect failed: {type(exc).__name__}: {exc}"
                    rec.last_packet = time.monotonic() - STALE_SECONDS + 10
    finally:
        try:
            feed.close_connection()
        except Exception:                                  # noqa: BLE001
            pass
        rec.writer.close()
        if rec.idxlog is not None:
            rec.idxlog.close()
        rec.write_health()
    h = rec.health()
    print(json.dumps(h))
    if selftest_seconds:
        print("selftest folder:", rec.writer.folder)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", type=float, default=0.0, metavar="SECONDS")
    ap.add_argument("--force", action="store_true", help="record even outside 09:05-15:32 or on a non-trading day")
    args = ap.parse_args()
    if not args.selftest and not args.force:
        sys.path.insert(0, str(ROOT))
        from trading_calendar import is_trading_day

        now = datetime.now(IST)
        if not is_trading_day(now.date())[0]:
            print("not a trading day")
            return 0
        if now.hour * 60 + now.minute >= END[0] * 60 + END[1]:
            print("market over")
            return 0
        start = now.replace(hour=START[0], minute=START[1], second=0, microsecond=0)
        if now < start:
            time.sleep((start - now).total_seconds())
    try:
        return run(ROOT, args.selftest)
    except Exception:                                      # noqa: BLE001 - leave a traceback behind instead of dying silently
        _log_crash(ROOT, "run")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
