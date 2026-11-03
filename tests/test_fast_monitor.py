import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import fast_monitor as fm
import paper_trade_journal as pj
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")


def T(m, s=0):
    return datetime(2026, 10, 14, 10, m, s, tzinfo=IST)


class FakeClient:
    def __init__(self, prices):
        self.prices = list(prices)
        self.calls = []

    def get_market_quotes(self, instruments, mode="quote"):
        self.calls.append(instruments)
        p = self.prices.pop(0) if len(self.prices) > 1 else self.prices[0]
        if isinstance(p, Exception):
            raise p
        return {"NSE_FNO": {"123": {"last_price": p}}}


def make(prices, **kw):
    tmp = tempfile.TemporaryDirectory()
    j = _journal(tmp.name, "2026-10-14", [_open_trade(entry_time="2026-10-14T10:00:00+05:30", option_stop=9.0, option_target1=50.0)])
    client = FakeClient(prices)
    mon = fm.FastPositionMonitor(j, client, interval=1, is_session=lambda now: True, **kw)
    return tmp, j, client, mon


class FastMonitorTests(unittest.TestCase):
    def test_settings(self):
        self.assertTrue(fm.enabled())
        with mock.patch.dict(os.environ, {"APLUS_FAST_MONITOR": "off"}):
            self.assertFalse(fm.enabled())
        self.assertEqual(fm.interval_seconds(), 3.0)
        with mock.patch.dict(os.environ, {"APLUS_FAST_MONITOR_SECONDS": "0.2"}):
            self.assertEqual(fm.interval_seconds(), 1.0)
        with mock.patch.dict(os.environ, {"APLUS_FAST_MONITOR_SECONDS": "junk"}):
            self.assertEqual(fm.interval_seconds(), 3.0)

    def test_marks_and_closes_a_position_between_scans(self):
        tmp, j, client, mon = make([10.5, 10.2, 8.8])
        self.addCleanup(tmp.cleanup)
        self.assertEqual(mon.tick(T(1)), [])
        self.assertEqual(j.trades[0]["last_option_price"], 10.5)
        mon.tick(T(1, 3))
        self.assertEqual(j.trades[0]["status"], "OPEN")
        closed = mon.tick(T(1, 6))                                                  # 8.8 is through the 9.0 stop: out at the first check that sees it
        self.assertEqual([t["exit_reason"] for t in closed], ["OPTION_STOP_LOSS"])
        self.assertEqual(j.trades[0]["exit_time"], T(1, 6).isoformat())
        self.assertEqual((mon.stats["ticks"], mon.stats["closed"]), (3, 1))
        self.assertTrue(j.state_path.exists())                                      # saved at once
        self.assertEqual(mon.tick(T(1, 9)), [])                                      # nothing open any more: no quote request
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[0], {"NSE_FNO": ["123"]})                      # only the open option is requested

    def test_no_request_outside_the_session_or_without_positions(self):
        tmp, j, client, mon = make([10.0])
        self.addCleanup(tmp.cleanup)
        mon.is_session = lambda now: False
        self.assertEqual(mon.tick(T(1)), [])
        self.assertEqual(client.calls, [])
        mon.is_session = lambda now: True
        j.trades[0]["status"] = "CLOSED"
        mon.tick(T(2))
        self.assertEqual(client.calls, [])

    def test_failed_fetch_never_marks_the_position_unavailable_and_falls_back(self):
        tmp, j, client, mon = make([RuntimeError("quote down")])
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(RuntimeError):
            mon.tick(T(1))
        self.assertNotIn("mark_status", j.trades[0])                                 # the scan loop owns "unavailable" handling
        good = FakeClient([10.4])
        broken = FakeClient([RuntimeError("dhan down")])

        class Hybrid:
            _dhan = broken
            get_market_quotes = good.get_market_quotes

        m2 = fm.FastPositionMonitor(j, Hybrid(), interval=1, is_session=lambda now: True)
        m2.tick(T(2))
        self.assertEqual((len(broken.calls), len(good.calls), j.trades[0]["last_option_price"]), (1, 1, 10.4))   # Dhan first, then the scanner's own client

    def test_journal_lock_serialises_two_threads(self):
        tmp, j, client, mon = make([10.5])
        self.addCleanup(tmp.cleanup)
        errors = []

        def hammer(fn):
            try:
                for _ in range(200):
                    fn()
            except Exception as exc:                                                # noqa: BLE001
                errors.append(exc)

        a = threading.Thread(target=hammer, args=(lambda: j.update_open_positions(option_quotes={"123": {"last_price": 10.3}}, when=T(1)),))
        b = threading.Thread(target=hammer, args=(lambda: (j.open_positions(T(1)), j.summary(T(1)), j.flush()),))
        a.start()
        b.start()
        a.join(20)
        b.join(20)
        self.assertEqual(errors, [])
        self.assertTrue(hasattr(j, "_lock"))
        self.assertIn("update_open_positions", pj.PaperTradeJournal.LOCKED_METHODS)

    def test_thread_starts_and_stops(self):
        tmp, j, client, mon = make([10.5])
        self.addCleanup(tmp.cleanup)
        mon.interval = 0.05
        mon.clock = lambda: T(1)
        mon.start()
        time.sleep(0.4)
        mon.stop()
        self.assertGreaterEqual(mon.stats["ticks"], 2)


if __name__ == "__main__":
    unittest.main()
