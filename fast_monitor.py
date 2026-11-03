"""Fast monitor for OPEN paper positions: checks their option prices and exit rules every few seconds instead of once per scan cycle (PAPER trades only; places no orders).

The scanner polls once a minute (INTRADAY_POLL_SECONDS), and that one loop was also the only thing watching open trades, so a stop, the profit ladder or a trail could only react at
one-minute points. Option prices swing several percent in a minute: on 22-23 Oct trades were stopped well past their stop level (KEI +33% then out at -9.5%, SRF -20% stop filled at -33%).

This runs beside the scan loop in its own thread: every APLUS_FAST_MONITOR_SECONDS (default 3) it asks for the prices of just the open options (one batched quote request, none when
nothing is open) and calls the SAME PaperTradeJournal.update_open_positions the scan loop uses, so every exit rule, ladder, trail, manual stop / exit and shadow behaves exactly as
before, only evaluated more often. A trade it closes is saved immediately. The journal serialises the two loops with a lock (see PaperTradeJournal).

    APLUS_FAST_MONITOR           ON (default) / OFF
    APLUS_FAST_MONITOR_SECONDS   3  (minimum 1; Dhan allows about one quote request a second)

It never force-closes at the session end (the scan loop still does that), never marks a position "unavailable" on a failed fetch (the scan loop handles that), and prefers the Dhan quote
endpoint directly so the Upstox request budget stays free for candles; if Dhan fails it tries the scanner's own client.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, time as clock_time, timedelta, timezone
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def enabled() -> bool:
    return os.getenv("APLUS_FAST_MONITOR", "ON").strip().upper() not in {"OFF", "0", "NO", "FALSE"}


def interval_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("APLUS_FAST_MONITOR_SECONDS", "3")))
    except ValueError:
        return 3.0


class FastPositionMonitor:
    def __init__(self, journal: Any, client: Any, *, interval: float = 3.0, is_session: Callable[[datetime], bool] | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.journal = journal
        self.client = client
        self.dhan = getattr(client, "_dhan", client)          # the Hybrid client wraps the Dhan client; quotes go to Dhan first so the Upstox budget stays for candles
        self.interval = max(1.0, float(interval))
        self.clock = clock or (lambda: datetime.now(IST))
        self.is_session = is_session or (lambda now: clock_time(9, 15) <= now.time() < clock_time(15, 30) and now.weekday() < 5)
        self.stats = {"ticks": 0, "quote_calls": 0, "closed": 0, "errors": 0, "last_error": ""}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_logged_error = 0.0

    def _fetch(self, ids: list[str]) -> Mapping[str, Any]:
        last: Exception | None = None
        for source in (self.dhan, self.client):
            try:
                self.stats["quote_calls"] += 1
                seg = source.get_market_quotes({"NSE_FNO": ids}, mode="quote").get("NSE_FNO", {})
                if isinstance(seg, Mapping) and seg:
                    return seg
            except Exception as exc:                          # noqa: BLE001 - try the next source
                last = exc
            if source is self.client:
                break
        if last is not None:
            raise last
        return {}

    def tick(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """One check. Returns the trades it closed (empty when nothing is open or the session is not running)."""
        now = now or self.clock()
        if not self.is_session(now):
            return []
        positions = self.journal.open_positions(now)
        ids = sorted({str(p.get("option_security_id") or "") for p in positions if str(p.get("option_security_id") or "")})
        if not ids:
            return []
        self.stats["ticks"] += 1
        quotes = self._fetch(ids)
        closed = self.journal.update_open_positions(option_quotes=quotes, when=now, force_close=False)
        if closed:
            self.stats["closed"] += len(closed)
            self.journal.flush()                                # a fast exit is saved at once, not at the next scan cycle
            logger.info("FAST_MONITOR closed %s", ", ".join(f"{t.get('symbol')} {t.get('exit_reason')} {t.get('exit_price')}" for t in closed))
        return list(closed)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:                            # noqa: BLE001 - a failed check just waits for the next one
                self.stats["errors"] += 1
                self.stats["last_error"] = f"{type(exc).__name__}: {exc}"
                if time.monotonic() - self._last_logged_error > 60:
                    self._last_logged_error = time.monotonic()
                    logger.warning("FAST_MONITOR check failed (retrying every %.0fs): %s", self.interval, self.stats["last_error"])

    def start(self) -> "FastPositionMonitor":
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="fast-monitor", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()


def start_for(scanner: Any) -> FastPositionMonitor | None:
    """Start the monitor for a scanner (called once when its run loop starts). None when switched off."""
    if not enabled():
        logger.info("Fast position monitor is OFF (APLUS_FAST_MONITOR)")
        return None
    from trading_calendar import is_trading_day

    def in_session(now: datetime) -> bool:
        return is_trading_day(now.date())[0] and scanner.settings.session_start <= now.time() < scanner.settings.session_stop

    scanner.paper_journal.async_alerts = True            # Telegram calls leave the journal lock at once, so a slow reply never delays a stop check
    mon = FastPositionMonitor(scanner.paper_journal, scanner.client, interval=interval_seconds(), is_session=in_session).start()
    logger.info("Fast position monitor started: open paper positions checked every %.0fs", mon.interval)
    return mon
