import os
import tempfile
import threading
import unittest
from pathlib import Path

from core.upstox_client import UpstoxClient, UpstoxLimit, _Budget, _SharedLedger, SHARED_CAPS, FLOOR_OWN_CAP, CHART_OWN_CAP


class SharedBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.tmp.name) / "b.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def budget(self, who, priority="high"):
        return _Budget(per_second=100000, per_minute=100000, per_30min=100000, shared=_SharedLedger(self.db, who=who), priority=priority)

    def test_two_processes_count_together(self):
        a, b = self.budget("scanner"), self.budget("collector", "low")
        for _ in range(10):
            a.take()
        for _ in range(5):
            b.take()
        u = a.shared.usage()
        self.assertEqual(u["last_30min"], 15)
        self.assertEqual(u["by_process"]["scanner"]["30min"], 10)
        self.assertEqual(u["by_process"]["collector"]["30min"], 5)

    def test_low_priority_stops_before_high(self):
        led = _SharedLedger(self.db, who="x")
        t = 1_000_000.0
        cap30, _ = SHARED_CAPS["low"]
        for i in range(cap30):                                    # spread over 25 minutes so only the 30-minute cap matters
            led.take("high", now=t + i * (1500.0 / cap30))
        now = t + 1500
        with self.assertRaises(UpstoxLimit):
            led.take("low", now=now)
        led.take("high", now=now)                                 # trading still has room

    def test_floor_still_works_when_low_is_starved_but_stops_at_top_cap(self):
        led = _SharedLedger(self.db, who="order_book_recorder.py")
        scanner = _SharedLedger(self.db, who="main.py")
        t = 6_000_000.0
        cap_low, _ = SHARED_CAPS["low"]
        for i in range(cap_low + 100):                            # the scanner has used more than the low cap (spread over 25 minutes)
            scanner.take("high", now=t + i * (1500.0 / (cap_low + 100)))
        now = t + 1500
        with self.assertRaises(UpstoxLimit):
            led.take("low", now=now)                              # a collector is locked out ...
        led.take("floor", now=now)                                # ... but a floor recorder is not

    def test_floor_stops_at_its_own_cap(self):
        led = _SharedLedger(self.db, who="futures_recorder.py")
        t = 7_000_000.0
        for i in range(FLOOR_OWN_CAP):
            led.take("floor", now=t + i * (1500.0 / FLOOR_OWN_CAP))          # spread over 25 minutes, so all inside the 30-minute window
        with self.assertRaises(UpstoxLimit):
            led.take("floor", now=t + 1500.0)
        other = _SharedLedger(self.db, who="order_book_recorder.py")
        other.take("floor", now=t + 1500.0)         # another floor process has its own allowance

    def test_floor_stops_at_the_top_cap(self):
        led = _SharedLedger(self.db, who="order_book_recorder.py")
        t = 8_000_000.0
        cap30, _ = SHARED_CAPS["floor"]
        for i in range(cap30):
            led.take("monitor", now=t + i * (1500.0 / cap30))
        with self.assertRaises(UpstoxLimit):
            led.take("floor", now=t + 1500)

    def test_chart_works_when_low_is_starved_and_only_its_own_calls_count(self):
        t = 9_000_000.0
        scanner = _SharedLedger(self.db, who="main.py")
        dash = _SharedLedger(self.db, who="aplus_live_pnl_dashboard.py")
        cap_low, _ = SHARED_CAPS["low"]
        for i in range(cap_low + 100):                            # scanner has used more than the low cap
            scanner.take("high", now=t + i * (1500.0 / (cap_low + 100)))
        now = t + 1500
        with self.assertRaises(UpstoxLimit):
            dash.take("low", now=now)                             # the dashboard's other calls are locked out ...
        for i in range(CHART_OWN_CAP):
            dash.take("chart", now=now + i * 0.5)                 # ... its chart calls are not, up to their own cap
        with self.assertRaises(UpstoxLimit):
            dash.take("chart", now=now + CHART_OWN_CAP * 0.5)
        u = dash.usage(now=now + CHART_OWN_CAP * 0.5 + 1)
        self.assertEqual(u["by_process"]["aplus_live_pnl_dashboard.py#chart"]["30min"], CHART_OWN_CAP)

    def test_other_dashboard_calls_do_not_use_up_the_chart_allowance(self):
        t = 9_500_000.0
        dash = _SharedLedger(self.db, who="aplus_live_pnl_dashboard.py")
        for i in range(CHART_OWN_CAP + 20):
            dash.take("high", now=t + i * 5.0)                    # lots of ordinary dashboard calls
        dash.take("chart", now=t + 1000.0)                        # the chart allowance is untouched

    def test_high_priority_stops_at_its_cap(self):
        led = _SharedLedger(self.db, who="x")
        t = 2_000_000.0
        cap30, _ = SHARED_CAPS["high"]
        for i in range(cap30):
            led.take("high", now=t + i * (1500.0 / cap30))
        with self.assertRaises(UpstoxLimit):
            led.take("high", now=t + 1500)

    def test_per_minute_cap_and_window_slides(self):
        led = _SharedLedger(self.db, who="x")
        t = 3_000_000.0
        _, cap60 = SHARED_CAPS["low"]
        for i in range(cap60):
            led.take("low", now=t + i * 0.1)
        with self.assertRaises(UpstoxLimit):
            led.take("low", now=t + 30)
        led.take("low", now=t + 120)                              # a minute later the window has moved on

    def test_rejected_call_is_not_recorded(self):
        led = _SharedLedger(self.db, who="x")
        t = 4_000_000.0
        _, cap60 = SHARED_CAPS["low"]
        for i in range(cap60):
            led.take("low", now=t + i * 0.1)
        for _ in range(5):
            with self.assertRaises(UpstoxLimit):
                led.take("low", now=t + 30)
        self.assertEqual(led.usage(now=t + 30)["last_30min"], cap60)

    def test_broken_ledger_never_blocks(self):
        led = _SharedLedger(Path(self.tmp.name) / "no" / "such" / "dir" / "\0bad", who="x")
        led.take("high")                                          # no exception: shared check is skipped
        led.take("low")

    def test_threads_cannot_overshoot(self):
        led = _SharedLedger(self.db, who="x")
        t = 5_000_000.0
        cap30, _ = SHARED_CAPS["low"]
        ok = []

        def work(k):
            mine = _SharedLedger(self.db, who=f"w{k}")
            for i in range(200):
                try:
                    mine.take("low", now=t + k * 0.001 + i * 0.2)
                    ok.append(1)
                except UpstoxLimit:
                    pass

        ts = [threading.Thread(target=work, args=(k,)) for k in range(4)]
        [x.start() for x in ts]
        [x.join() for x in ts]
        self.assertLessEqual(len(ok), SHARED_CAPS["low"][1])      # the per-minute cap binds here (all inside 40 s of data time)
        self.assertEqual(led.usage(now=t + 41)["last_30min"], len(ok))


class ClientWiringTests(unittest.TestCase):
    def test_injected_session_never_joins_the_live_ledger(self):
        c = UpstoxClient(token="t", session=object(), master=[])
        self.assertIsNone(c.budget.shared)

    def test_real_client_joins_and_priority_comes_from_argument_or_env(self):
        os.environ.pop("APLUS_UPSTOX_PRIORITY", None)
        c = UpstoxClient(token="t")
        self.assertIsNotNone(c.budget.shared)
        self.assertEqual(c.budget.priority, "high")
        self.assertEqual(UpstoxClient(token="t", priority="low").budget.priority, "low")
        self.assertEqual(UpstoxClient(token="t", priority="floor").budget.priority, "floor")
        self.assertEqual(UpstoxClient(token="t", priority="chart").budget.priority, "chart")
        os.environ["APLUS_UPSTOX_PRIORITY"] = "low"
        try:
            self.assertEqual(UpstoxClient(token="t").budget.priority, "low")
        finally:
            os.environ.pop("APLUS_UPSTOX_PRIORITY", None)

    def test_can_be_switched_off(self):
        os.environ["APLUS_UPSTOX_SHARED_BUDGET"] = "0"
        try:
            self.assertIsNone(UpstoxClient(token="t").budget.shared)
        finally:
            os.environ.pop("APLUS_UPSTOX_SHARED_BUDGET", None)


if __name__ == "__main__":
    unittest.main()
