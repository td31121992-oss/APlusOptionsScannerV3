import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.upstox_client import SHARED_CAPS, UpstoxLimit, _SharedLedger, _cap_for, priority_scope

IST = timezone(timedelta(hours=5, minutes=30))


def ts(h, m):
    return datetime(2026, 11, 19, h, m, tzinfo=IST).timestamp()


class ReserveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.led = _SharedLedger(Path(self.tmp.name) / "b.sqlite3", who="t")

    def tearDown(self):
        self.tmp.cleanup()

    def test_low_cap_is_tighter_in_the_opening_45_minutes(self):
        self.assertLess(_cap_for("low", ts(9, 40))[0], SHARED_CAPS["low"][0])
        self.assertEqual(_cap_for("low", ts(10, 5)), SHARED_CAPS["low"])
        self.assertEqual(_cap_for("high", ts(9, 40)), SHARED_CAPS["high"])

    def test_monitor_keeps_a_slice_the_scanner_cannot_use(self):
        t = ts(11, 0)
        n = SHARED_CAPS["high"][0]
        for i in range(n):
            self.led.take("high", now=t - 1500 + i * (1500.0 / n))
        with self.assertRaises(UpstoxLimit):
            self.led.take("high", now=t)
        self.led.take("monitor", now=t)                      # still allowed
        with priority_scope("monitor"):
            self.led.take("high", now=t)                     # scope upgrades the caller to monitor

    def test_scope_resets_after_exit(self):
        t = ts(11, 0)
        n = SHARED_CAPS["high"][0]
        for i in range(n):
            self.led.take("high", now=t - 1500 + i * (1500.0 / n))
        with priority_scope("monitor"):
            pass
        with self.assertRaises(UpstoxLimit):
            self.led.take("high", now=t)


if __name__ == "__main__":
    unittest.main()
