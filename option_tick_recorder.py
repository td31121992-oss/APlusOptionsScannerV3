"""Option-contract tick recorder for the contracts we hold (DATA ONLY: never touches the scanner or any trade).

The tick recorder streams the 213 stocks. The option contract a paper trade actually holds was only seen once a second at best (the fast monitor) or once a minute (the quote tape), so its real
path, spread and queue are lost between marks. This opens its own Dhan live-feed connection and, whenever the paper journal has an OPEN trade, subscribes that option contract in Full mode and
writes every packet:

    data/option_ticks/<day>/<option_security_id>_<SYMBOL>.csv.gz     columns: ts, ltp, ltq, vol, oi, tbq, tsq, bid, bq, ask, aq, bsum5, asum5, tq, side, mid, spread_pct
    data/option_ticks/health.json                                      packets, contracts followed, restarts, last error (every 30 s)

    tq     quantity traded since the previous packet     side   B / S as in tick_recorder.py (buyer / seller initiated)     spread_pct   (ask - bid) / ask, %
The journal is read every 2 seconds, so a contract is subscribed within about 2-3 seconds of the entry and stays subscribed until the end of the day. It reconnects if the feed goes quiet for
a minute while a contract is followed. Runs 09:14-15:32 IST on trading days (scheduled task APlus_Option_Tick_Recorder).

    python option_tick_recorder.py                run until 15:32
    python option_tick_recorder.py --selftest N   connect for N seconds with a placeholder contract list, write nothing permanent
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
JOURNAL = ("data", "intraday_movement", "paper_trade_journal.json")
FIELDS = ["ts", "ltp", "ltq", "vol", "oi", "tbq", "tsq", "bid", "bq", "ask", "aq", "bsum5", "asum5", "tq", "side", "mid", "spread_pct"]
START, END = (9, 14), (15, 32)
STALE_SECONDS = 60
REFRESH_SECONDS = 2.0


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def open_contracts(journal_path: Path, day: str) -> dict[str, dict[str, str]]:
    """option_security_id -> {symbol, option_type, strike} for today's OPEN paper trades."""
    try:
        trades = json.loads(journal_path.read_text(encoding="utf-8")).get("trades") or []
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, str]] = {}
    for t in trades:
        sid = str(t.get("option_security_id") or "").strip()
        if sid and str(t.get("status") or "").upper() == "OPEN" and str(t.get("entry_time") or "").startswith(day):
            out[sid] = {"symbol": str(t.get("symbol") or "UNKNOWN"), "option_type": str(t.get("option_type") or ""), "strike": str(t.get("strike") or "")}
    return out


def packet_row(data: Mapping[str, Any], prev: Mapping[str, Any] | None, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """One CSV row and the new 'previous' state from a parsed Full packet (the dict the dhanhq library produces)."""
    from tick_recorder import packet_row as stock_row

    row, state = stock_row(dict(data), "OPT", prev, now)
    bid, ask = _f(row.get("bid")), _f(row.get("ask"))
    out = {k: row.get(k, "") for k in FIELDS if k not in ("oi", "mid", "spread_pct")}
    out["oi"] = int(_f(data.get("OI")))
    out["mid"] = round((bid + ask) / 2.0, 3) if bid > 0 and ask > 0 else ""
    out["spread_pct"] = round((ask - bid) / ask * 100.0, 2) if bid > 0 and ask >= bid else ""
    return out, state


class OptionTickWriter:
    def __init__(self, root: Path, day: str) -> None:
        self.folder = root / "data" / "option_ticks" / day
        self.folder.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, Any] = {}
        self._last_flush = time.monotonic()
        self._lock = threading.Lock()

    def write(self, name: str, row: Mapping[str, Any]) -> None:
        with self._lock:
            f = self._files.get(name)
            if f is None:
                path = self.folder / f"{name}.csv.gz"
                try:                               # see tick_gz.py: a cut-off member from an earlier crash must not hide what is appended now
                    import tick_gz

                    tick_gz.repair(path) if path.exists() else None
                except Exception:                  # noqa: BLE001
                    pass
                new = not path.exists()
                f = gzip.open(path, "at", encoding="utf-8", newline="")
                if new:
                    f.write(",".join(FIELDS) + "\n")
                self._files[name] = f
            f.write(",".join(str(row.get(k, "")) for k in FIELDS) + "\n")
            if time.monotonic() - self._last_flush > 3:
                for h in self._files.values():
                    h.flush()
                self._last_flush = time.monotonic()

    def close(self) -> None:
        with self._lock:
            for h in self._files.values():
                try:
                    h.close()
                except Exception:                           # noqa: BLE001
                    pass
            self._files.clear()


class Recorder:
    def __init__(self, root: Path, day: str | None = None) -> None:
        self.root = root
        self.day = day or date.today().isoformat()
        self.writer = OptionTickWriter(root, self.day)
        self.contracts: dict[str, dict[str, str]] = {}
        self.prev: dict[str, dict[str, Any]] = {}
        self.packets = 0
        self.restarts = 0
        self.last_packet = 0.0
        self.last_sub = 0.0                                  # when a contract was last subscribed (the clock for 'went quiet' starts here, not at process start)
        self.last_error = ""

    def on_message(self, feed: Any, data: Any) -> None:
        if not isinstance(data, dict) or data.get("type") != "Full Data":
            return
        sid = str(data.get("security_id"))
        info = self.contracts.get(sid)
        if not info:
            return                                         # the placeholder subscription or a contract we no longer follow
        self.packets += 1
        self.last_packet = time.monotonic()
        row, state = packet_row(data, self.prev.get(sid), datetime.now(IST))
        self.prev[sid] = state
        self.writer.write(f"{sid}_{info['symbol']}", row)

    def on_error(self, feed: Any, error: Exception) -> None:
        self.last_error = f"{type(error).__name__}: {error}"

    def health(self) -> dict[str, Any]:
        return {"day": self.day, "updated": datetime.now(IST).isoformat(timespec="seconds"), "contracts": sorted(self.contracts), "packets": self.packets, "restarts": self.restarts,
                "seconds_since_packet": None if not self.last_packet else round(time.monotonic() - self.last_packet, 1), "last_error": self.last_error}

    def write_health(self) -> None:
        try:
            p = self.root / "data" / "option_ticks" / "health.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.health()), encoding="utf-8")
        except OSError:
            pass


def sync_subscriptions(rec: Recorder, feed: Any, wanted: Mapping[str, Mapping[str, str]], segment: Any, mode: Any) -> list[str]:
    """Subscribe the contracts that are newly open (never unsubscribes: a closed trade's contract is cheap to keep until the end of the day). Returns the ids added."""
    new = [sid for sid in wanted if sid not in rec.contracts]
    for sid in new:
        rec.contracts[sid] = dict(wanted[sid])
    if new:
        rec.last_sub = time.monotonic()
        feed.subscribe_symbols([(segment, sid, mode) for sid in new])
    return new


def is_stale(rec: "Recorder", now: float) -> bool:
    """A followed contract has gone quiet: contracts are subscribed and STALE_SECONDS have passed since the later of the last packet and the last subscription.
    (Measuring from process start instead made the first contract of the day, added 20 minutes after the start, look stale at once: the recorder then tried to reconnect and hung, 26 Oct.)"""
    ref = max(rec.last_packet, rec.last_sub)
    return bool(rec.contracts) and ref > 0 and now - ref > STALE_SECONDS


def close_feed(feed: Any, timeout: float = 5.0) -> None:
    """feed.close_connection() on a daemon thread: a hung websocket close must never stop the main loop (it is the loop that writes the health file and takes new contracts)."""
    t = threading.Thread(target=lambda: _quiet(feed.close_connection), daemon=True)
    t.start()
    t.join(timeout)


def _quiet(fn: Callable[[], Any]) -> None:
    try:
        fn()
    except Exception:                                      # noqa: BLE001
        pass


def _log_crash(root: Path, where: str) -> None:
    import traceback

    try:
        p = root / "data" / "option_ticks"
        p.mkdir(parents=True, exist_ok=True)
        with (p / "recorder_error.log").open("a", encoding="utf-8") as h:
            h.write(f"--- {datetime.now(IST).isoformat(timespec='seconds')} in {where}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def _use_upstox() -> bool:
    sys.path.insert(0, str(ROOT))
    import upstox_feed

    return upstox_feed.feed_provider() == "UPSTOX"


def _feed_constants() -> tuple[Any, Any]:
    """(segment, mode) for an option contract subscription: Upstox's names, or Dhan's MarketFeed constants."""
    if _use_upstox():
        return "NSE_FNO", "full"
    from dhanhq import MarketFeed

    return MarketFeed.NSE_FNO, MarketFeed.Full


def _start_feed(rec: Recorder) -> Any:
    if _use_upstox():
        try:
            from upstox_feed import UpstoxMarketFeed

            feed = UpstoxMarketFeed([("IDX_I", "13", "ticker")], rec.on_message, rec.on_error)       # NIFTY keeps the connection alive until the first option is subscribed
            feed.start()
            return feed
        except Exception as exc:                           # noqa: BLE001 - no Upstox token / mapping problem: follow the contracts on Dhan instead of not at all
            rec.last_error = f"Upstox feed unavailable, using Dhan: {type(exc).__name__}: {exc}"
    from dhanhq import DhanContext, MarketFeed
    from tick_recorder import _credentials

    cid, token = _credentials(ROOT)
    initial = [(MarketFeed.IDX, "13", MarketFeed.Ticker)]       # NIFTY index keeps the connection alive until the first option is subscribed
    feed = MarketFeed(DhanContext(cid, token), initial, "v2", on_message=rec.on_message, on_error=rec.on_error)
    feed.start()
    return feed


def run(root: Path = ROOT, selftest_seconds: float = 0.0) -> int:
    sys.path.insert(0, str(root))
    segment, mode = _feed_constants()

    rec = Recorder(root if not selftest_seconds else Path(__import__("tempfile").mkdtemp(prefix="opt_ticks_selftest_")))
    end = datetime.now(IST).replace(hour=END[0], minute=END[1], second=0, microsecond=0)
    feed = _start_feed(rec)
    t0 = time.monotonic()
    last_health = last_refresh = 0.0
    journal = root.joinpath(*JOURNAL)
    try:
        while True:
            time.sleep(0.5)
            now = time.monotonic()
            if selftest_seconds and now - t0 >= selftest_seconds:
                break
            if not selftest_seconds and datetime.now(IST) >= end:
                break
            if now - last_refresh >= REFRESH_SECONDS:
                last_refresh = now
                try:
                    sync_subscriptions(rec, feed, open_contracts(journal, rec.day), segment, mode)
                except Exception as exc:                     # noqa: BLE001 - try again at the next refresh
                    rec.last_error = f"subscribe: {type(exc).__name__}: {exc}"
                    _log_crash(root, "subscribe")
            if now - last_health > 30:
                rec.write_health()
                last_health = now
            if not selftest_seconds and is_stale(rec, now) and datetime.now(IST).hour * 60 + datetime.now(IST).minute >= START[0] * 60 + START[1]:
                rec.restarts += 1                            # a followed contract went quiet during the session: reconnect and subscribe them all again
                close_feed(feed)
                time.sleep(2)
                try:
                    wanted = dict(rec.contracts)
                    rec.contracts = {}
                    feed = _start_feed(rec)
                    time.sleep(2)
                    sync_subscriptions(rec, feed, wanted, segment, mode)
                    rec.last_packet = time.monotonic()
                except Exception as exc:                     # noqa: BLE001
                    _log_crash(root, "reconnect")
                    rec.last_error = f"reconnect failed: {type(exc).__name__}: {exc}"
                    rec.last_packet = time.monotonic() - STALE_SECONDS + 10
                    rec.last_sub = rec.last_packet
    finally:
        close_feed(feed)
        rec.writer.close()
        rec.write_health()
    print(json.dumps(rec.health()))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", type=float, default=0.0, metavar="SECONDS")
    ap.add_argument("--force", action="store_true", help="record even outside 09:14-15:32 or on a non-trading day")
    a = ap.parse_args()
    if not a.selftest and not a.force:
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
        return run(ROOT, a.selftest)
    except Exception:                                        # noqa: BLE001 - leave a traceback behind instead of dying silently
        _log_crash(ROOT, "run")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
