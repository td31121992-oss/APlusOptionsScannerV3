import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import manual_orders as mo
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")


def T(m, s=0):
    return datetime(2026, 10, 14, 10, m, s, tzinfo=IST)


class ManualOrderFileTests(unittest.TestCase):
    def test_latest_wish_per_trade_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            mo.add(tmp, "A", "STOP", 9.5, when=T(1))
            mo.add(tmp, "A", "STOP", 9.8, when=T(2))
            mo.add(tmp, "B", "STOP", 5.0, when=T(2))
            mo.add(tmp, "B", "CLEAR", when=T(3))
            mo.add(tmp, "C", "EXIT", when=T(4))
            st = mo.desired_state(mo.read(tmp, "2026-10-14"))
            self.assertEqual(st["A"]["stop"], 9.8)
            self.assertIsNone(st["B"]["stop"])
            self.assertTrue(st["C"]["exit_at"])

    def test_bad_commands_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args in (("", "EXIT"), ("A", "NOPE"), ("A", "STOP", 0)):
                with self.assertRaises(ValueError):
                    mo.add(tmp, *args)

    def test_validate_stop(self):
        trade = {"status": "OPEN", "last_option_price": 12.0, "option_stop": 8.0, "ladder_stop": 10.3}
        self.assertTrue(mo.validate_stop(trade, 11.0)[0])
        self.assertFalse(mo.validate_stop(trade, 10.0)[0])         # not above the current (ladder) stop
        self.assertFalse(mo.validate_stop(trade, 12.0)[0])         # at/above the last price: use Exit now
        self.assertFalse(mo.validate_stop({**trade, "status": "CLOSED"}, 11.0)[0])


class JournalAppliesManualCommands(unittest.TestCase):
    def _journal(self, tmp):
        j = _journal(tmp, "2026-10-14", [_open_trade(entry_time="2026-10-14T10:00:00+05:30")])
        j.manual_root = Path(tmp)
        return j

    def _tick(self, j, price, minute):
        return j.update_open_positions(option_quotes={"123": {"last_price": price}}, when=T(minute))

    def test_manual_stop_fires_as_manual_stop_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self._journal(tmp)
            self._tick(j, 10.4, 1)                                # open, original stop 9.0
            mo.add(tmp, "PT-TEST-1", "STOP", 10.0, when=T(2))
            self.assertEqual(self._tick(j, 10.3, 3), [])         # above the manual stop: still open
            self.assertEqual(j.trades[0]["manual_stop"], 10.0)
            closed = self._tick(j, 9.95, 4)
            self.assertEqual(len(closed), 1)
            self.assertEqual((closed[0]["exit_reason"], closed[0]["exit_price"]), ("MANUAL_STOP_LOSS", 9.95))

    def test_manual_stop_below_current_stop_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self._journal(tmp)
            mo.add(tmp, "PT-TEST-1", "STOP", 8.0, when=T(1))     # below the original stop 9.0: would loosen risk
            self.assertEqual(self._tick(j, 9.5, 2), [])
            closed = self._tick(j, 8.9, 3)                        # the ORIGINAL stop still protects
            self.assertEqual(closed[0]["exit_reason"], "OPTION_STOP_LOSS")

    def test_exit_now_closes_at_the_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self._journal(tmp)
            self.assertEqual(self._tick(j, 10.2, 1), [])
            mo.add(tmp, "PT-TEST-1", "EXIT", when=T(2))
            closed = self._tick(j, 10.25, 3)
            self.assertEqual((closed[0]["status"], closed[0]["exit_reason"], closed[0]["exit_price"]), ("CLOSED", "MANUAL_EXIT", 10.25))

    def test_clear_removes_the_manual_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self._journal(tmp)
            mo.add(tmp, "PT-TEST-1", "STOP", 10.0, when=T(1))
            self._tick(j, 10.4, 2)
            self.assertEqual(j.trades[0]["manual_stop"], 10.0)
            mo.add(tmp, "PT-TEST-1", "CLEAR", when=T(3))
            self.assertEqual(self._tick(j, 9.9, 4), [])           # no manual stop any more; original stop is 9.0
            self.assertNotIn("manual_stop", j.trades[0])

    def test_switch_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["APLUS_MANUAL_CONTROLS"] = "OFF"
            self.addCleanup(os.environ.pop, "APLUS_MANUAL_CONTROLS", None)
            j = self._journal(tmp)
            mo.add(tmp, "PT-TEST-1", "EXIT", when=T(1))
            self.assertEqual(self._tick(j, 10.2, 2), [])


if __name__ == "__main__":
    unittest.main()
