import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"                  # tests must never send alerts

import paper_trade_journal as pj
from paper_trade_journal import PaperTradeJournal

IST = ZoneInfo("Asia/Kolkata")


class Cost5Tests(unittest.TestCase):
    def test_floor_steps(self):
        f = pj.cost5_floor
        self.assertEqual(f(100.0, 104.9), 0.0)                    # not yet +5%
        self.assertEqual(f(100.0, 105.0), 100.0)                  # +5% -> stop at cost (the live ladder says -15%)
        self.assertEqual(f(100.0, 109.9), 100.0)
        self.assertAlmostEqual(f(100.0, 110.0), 103.0)            # the rest of the ladder is unchanged
        self.assertAlmostEqual(f(100.0, 120.0), 113.0)
        self.assertAlmostEqual(f(100.0, 130.0), 122.0)
        self.assertAlmostEqual(f(100.0, 140.0), 126.0)            # +2 points per further +5%
        self.assertEqual(f(0.0, 5.0), 0.0)

    def test_only_the_first_step_differs_from_the_live_ladder(self):
        for high in (104.0, 110.0, 119.9, 120.0, 135.0, 160.0):
            self.assertAlmostEqual(pj.cost5_floor(100.0, high), pj.user_ladder_floor(100.0, high))
        self.assertAlmostEqual(pj.user_ladder_floor(100.0, 107.0), 85.0)
        self.assertAlmostEqual(pj.cost5_floor(100.0, 107.0), 100.0)

    def test_registered_and_recorded_like_the_other_shadows(self):
        self.assertIn("cost5", pj.STOP_SHADOW_NAMES)
        floors = pj.PaperTradeJournal._stop_shadow_floors({}, 100.0, 107.0)
        self.assertEqual((floors["cost5"], floors["user_ladder"]), (100.0, 85.0))

    def test_the_journal_records_what_cost5_would_have_done_without_touching_the_trade(self):
        os.environ["APLUS_EXIT_LADDER_MODE"] = "SHADOW"
        self.addCleanup(os.environ.pop, "APLUS_EXIT_LADDER_MODE", None)
        with tempfile.TemporaryDirectory() as tmp:
            journal = PaperTradeJournal(state_dir=Path(tmp, "state"), report_dir=Path(tmp, "reports"))
            journal.notifier = type("N", (), {"notify_exit": lambda *a: None, "notify_entry": lambda *a: None})()
            journal.trading_date = "2026-10-29"
            journal.trades = [{"paper_trade_id": "PT-20261029-1", "symbol": "TEST", "direction": "BULLISH", "status": "OPEN", "option_security_id": "123", "option_transaction": "BUY",
                               "entry_price": 10.0, "quantity": 1000, "capital_deployed": 10000.0, "option_stop": 8.0, "option_target1": 50.0, "spread_percent": 1.5,
                               "entry_time": "2026-10-29T10:00:00+05:30", "last_option_price": 10.0, "highest_option_price": 10.0, "lowest_option_price": 10.0}]
            for i, price in enumerate((10.6, 9.9)):                  # +6% reached, then back below cost (the live stop is 8.5, so the real trade stays open)
                journal.update_open_positions(option_quotes={"123": {"last_price": price}}, when=datetime(2026, 10, 29, 10, 1 + i, tzinfo=IST))
            t = journal.trades[0]
        self.assertEqual(t["status"], "OPEN")
        self.assertEqual((t["shadow_cost5_exit_price"], t["shadow_cost5_floor"]), (9.9, 10.0))
        self.assertNotIn("shadow_user_ladder_exit_price", t)                   # the live ladder's -15% stop was not reached

    def test_a_shadow_that_never_triggered_ends_with_the_real_exit(self):
        trade = {}
        pj.PaperTradeJournal._finish_stop_shadows(trade, datetime(2026, 10, 29, 15, 20), 90.0)
        self.assertEqual((trade["shadow_cost5_exit_price"], trade["shadow_cost5_at_real_exit"]), (90.0, True))


if __name__ == "__main__":
    unittest.main()
