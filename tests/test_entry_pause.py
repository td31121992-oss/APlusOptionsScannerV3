import tempfile
import unittest
from datetime import date, datetime

import entry_pause as ep

DAY = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 11, 30)


class EntryPauseTests(unittest.TestCase):
    def test_default_is_not_blocked_and_missing_file_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ep.check(tmp, 0, 500000, DAY), (False, ""))

    def test_manual_pause_applies_today_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep.set_state(tmp, paused=True, now=NOW)
            self.assertEqual(ep.check(tmp, 0, 500000, DAY), (True, "PAUSED_BY_USER"))
            self.assertEqual(ep.check(tmp, 0, 500000, date(2026, 10, 16)), (False, ""))
            ep.set_state(tmp, paused=False, now=NOW)
            self.assertEqual(ep.check(tmp, 0, 500000, DAY), (False, ""))

    def test_day_target_blocks_once_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep.set_state(tmp, target_pct=7, now=NOW)
            self.assertFalse(ep.check(tmp, 34000, 500000, DAY)[0])           # 6.8%
            blocked, why = ep.check(tmp, 35000, 500000, DAY)                  # 7.0%
            self.assertTrue(blocked)
            self.assertIn("7", why)
            self.assertFalse(ep.check(tmp, 90000, 500000, date(2026, 10, 16))[0])   # a target never carries over
            ep.set_state(tmp, clear_target=True, now=NOW)
            self.assertFalse(ep.check(tmp, 90000, 500000, DAY)[0])

    def test_bad_target_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ep.set_state(tmp, target_pct=0, now=NOW)
            with self.assertRaises(ValueError):
                ep.set_state(tmp, target_pct=150, now=NOW)

    def test_day_pnl_counts_only_that_day_and_prefers_total(self):
        trades = [{"entry_time": "2026-10-15T09:30:00", "total_pnl": 1000, "net_pnl": 900},
                  {"entry_time": "2026-10-15T10:00:00", "net_pnl": -250},
                  {"entry_time": "2026-10-14T10:00:00", "total_pnl": 5000}]
        self.assertEqual(ep.day_pnl(trades, "2026-10-15"), 750.0)

    def test_status_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep.set_state(tmp, paused=True, target_pct=10, now=NOW)
            s = ep.status(tmp, 25000, 500000, DAY)
            self.assertTrue(s["paused"] and s["blocked"])
            self.assertEqual((s["target_pct"], s["day_pct"]), (10, 5.0))


if __name__ == "__main__":
    unittest.main()


class HeartbeatTests(unittest.TestCase):
    def test_scanner_ready_follows_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(ep.scanner_ready(tmp))
            ep.heartbeat(tmp)
            self.assertTrue(ep.scanner_ready(tmp))
            self.assertFalse(ep.scanner_ready(tmp, now=datetime.now().replace(year=2030)))
