import unittest

import paper_trade_journal as pj
import stop_view


class Ladder2Tests(unittest.TestCase):
    def lock(self, gain):
        f = pj.ladder2_floor(100.0, 100.0 + gain)
        return None if f == 0 else round(f - 100.0, 4)

    def test_steps(self):
        self.assertIsNone(self.lock(9.9))                     # no step below +10%: the initial -20% stop stays
        self.assertEqual(self.lock(10), 3.0)
        self.assertEqual(self.lock(19.9), 3.0)
        self.assertEqual(self.lock(20), 12.0)
        self.assertEqual(self.lock(24.9), 12.0)
        self.assertEqual(self.lock(25), 14.0)
        self.assertEqual(self.lock(29.9), 14.0)
        self.assertEqual(self.lock(30), 22.0)
        self.assertEqual(self.lock(34.9), 22.0)
        self.assertEqual(self.lock(35), 24.0)
        self.assertEqual(self.lock(50), 30.0)

    def test_lock_never_moves_down_as_the_peak_rises(self):
        last = -1.0
        for g in range(0, 120):
            f = pj.ladder2_floor(100.0, 100.0 + g)
            self.assertGreaterEqual(f, last)
            last = f

    def test_stop_view_in_ladder2_mode(self):
        t = {"entry_price": 100, "highest_option_price": 121, "option_stop": 80}
        s = stop_view.stop_state(t, "ENFORCE2")
        self.assertEqual(s["cur_sl"], 112.0)
        self.assertIn("125.00", s["sl_next"])
        s = stop_view.stop_state({"entry_price": 100, "highest_option_price": 105, "option_stop": 80}, "ENFORCE2")
        self.assertEqual(s["cur_sl"], 80.0)
        self.assertIn("110.00", s["sl_next"])
        s = stop_view.stop_state({"entry_price": 100, "highest_option_price": 127, "option_stop": 80}, "ENFORCE2")
        self.assertIn("130.00", s["sl_next"])
        self.assertIn("122.00", s["sl_next"])                 # T3 at +30% jumps the lock to +22%

    def test_mode_is_accepted(self):
        import os
        old = os.environ.get("APLUS_EXIT_LADDER_MODE")
        try:
            os.environ["APLUS_EXIT_LADDER_MODE"] = "ENFORCE2"
            self.assertEqual(pj.PaperTradeJournal._exit_ladder_mode(), "ENFORCE2")
        finally:
            if old is None:
                os.environ.pop("APLUS_EXIT_LADDER_MODE", None)
            else:
                os.environ["APLUS_EXIT_LADDER_MODE"] = old


class Ladder2ShadowTests(unittest.TestCase):
    def test_registered_and_floor_recorded(self):
        self.assertIn("ladder2", pj.STOP_SHADOW_NAMES)
        floors = pj.PaperTradeJournal._stop_shadow_floors({}, 100.0, 121.0)
        self.assertEqual((round(floors["ladder2"], 2), round(floors["user_ladder"], 2)), (112.0, 113.0))

    def test_the_journal_records_what_ladder2_would_have_done_without_touching_the_trade(self):
        import os, tempfile
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        IST = timezone(timedelta(hours=5, minutes=30))
        os.environ["APLUS_EXIT_LADDER_MODE"] = "SHADOW"
        self.addCleanup(os.environ.pop, "APLUS_EXIT_LADDER_MODE", None)
        with tempfile.TemporaryDirectory() as tmp:
            journal = pj.PaperTradeJournal(state_dir=Path(tmp, "state"), report_dir=Path(tmp, "reports"))
            journal.notifier = type("N", (), {"notify_exit": lambda *a: None, "notify_entry": lambda *a: None})()
            journal.trading_date = "2026-11-24"
            journal.trades = [{"paper_trade_id": "PT-20261124-1", "symbol": "TEST", "direction": "BULLISH", "status": "OPEN", "option_security_id": "123", "option_transaction": "BUY",
                               "entry_price": 10.0, "quantity": 1000, "capital_deployed": 10000.0, "option_stop": 8.0, "option_target1": 50.0, "spread_percent": 1.5,
                               "entry_time": "2026-11-24T10:00:00+05:30", "last_option_price": 10.0, "highest_option_price": 10.0, "lowest_option_price": 10.0}]
            for i, price in enumerate((11.2, 10.2)):             # +12% reached (lock +3% = 10.3), then 10.2: the shadow stops, the real stop (8.0) does not
                journal.update_open_positions(option_quotes={"123": {"last_price": price}}, when=datetime(2026, 11, 24, 10, 1 + i, tzinfo=IST))
            t = journal.trades[0]
        self.assertEqual(t["status"], "OPEN")
        self.assertEqual((t["shadow_ladder2_exit_price"], t["shadow_ladder2_floor"]), (10.2, 10.3))


if __name__ == "__main__":
    unittest.main()
