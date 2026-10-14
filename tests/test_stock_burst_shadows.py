import os
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import paper_trade_journal as pj
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 10, 14, 10, 0, tzinfo=IST)


class StockBurstShadowTests(unittest.TestCase):
    def journal(self, tmp):
        return _journal(tmp, "2026-10-14", [_open_trade(underlying_entry=100.0, option_type="CE", entry_time="2026-10-14T10:00:00+05:30",
                                                        option_stop=7.0, option_target1=50.0)])

    def step(self, j, minute, stock, option):
        j.trades[0]["last_option_price"] = option
        j.record_stock_response({"TEST": stock}, T0 + timedelta(minutes=minute))

    def test_names_registered(self):
        for n in ("sbg40", "sbg60", "sstall10"):
            self.assertIn(n, pj.STOP_SHADOW_NAMES)

    def test_giveback_rules_fire_in_order_with_the_option_price_at_that_moment(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self.journal(tmp)
            t = j.trades[0]
            self.step(j, 1, 100.4, 10.5)        # +0.4%: below the 0.5% arm
            self.assertNotIn("shadow_sbg40_exit_at", t)
            self.step(j, 3, 101.0, 11.8)        # best so far +1.0%
            self.step(j, 5, 100.7, 11.3)        # gave back 30%: nothing yet
            self.assertNotIn("shadow_sbg40_exit_at", t)
            self.step(j, 7, 100.55, 11.0)       # gave back 45%: sbg40 fires at option 11.0
            self.assertEqual(t["shadow_sbg40_exit_price"], 11.0)
            self.assertNotIn("shadow_sbg60_exit_at", t)
            self.step(j, 9, 100.35, 10.6)       # 65%: sbg60 fires
            self.assertEqual(t["shadow_sbg60_exit_price"], 10.6)
            self.assertEqual(t["status"], "OPEN")                          # the real trade is untouched

    def test_stall_rule_needs_ten_quiet_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self.journal(tmp)
            t = j.trades[0]
            self.step(j, 2, 100.9, 11.6)
            self.step(j, 8, 100.85, 11.4)       # 6 minutes since the best: not yet
            self.assertNotIn("shadow_sstall10_exit_at", t)
            self.step(j, 13, 100.8, 11.2)       # 11 minutes: fires
            self.assertEqual(t["shadow_sstall10_exit_price"], 11.2)

    def test_new_best_resets_the_stall_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self.journal(tmp)
            t = j.trades[0]
            self.step(j, 2, 100.9, 11.6)
            self.step(j, 9, 101.2, 12.0)        # new best at minute 9
            self.step(j, 15, 101.1, 11.9)       # only 6 minutes since the new best
            self.assertNotIn("shadow_sstall10_exit_at", t)
            self.assertEqual(t["stock_move_fav_max_pct"], 1.2)


if __name__ == "__main__":
    unittest.main()
