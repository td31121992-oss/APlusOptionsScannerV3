import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import paper_trade_journal as pj
import trade_review as tr
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")


def T(m):
    return datetime(2026, 10, 14, 10, m, tzinfo=IST)


class CashTargetShadowTests(unittest.TestCase):
    def run_prices(self, prices, **over):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-14", [_open_trade(entry_time="2026-10-14T10:00:00+05:30", option_stop=7.0, option_target1=50.0, **over)])
            for i, p in enumerate(prices):
                j.update_open_positions(option_quotes={"123": {"last_price": p}}, when=T(1 + i))
            return dict(j.trades[0])

    def test_names_registered(self):
        for n in ("cash10", "cash15", "cash20"):
            self.assertIn(n, pj.STOP_SHADOW_NAMES)

    def test_each_target_fires_at_its_own_level_and_real_trade_is_untouched(self):
        t = self.run_prices([10.4, 11.2, 11.6, 12.1, 11.9])                 # entry 10.0: +12% then +16% then +21%
        self.assertEqual(t["status"], "OPEN")
        self.assertAlmostEqual(t["shadow_cash10_exit_price"], 11.0, places=2)
        self.assertAlmostEqual(t["shadow_cash15_exit_price"], 11.5, places=2)
        self.assertAlmostEqual(t["shadow_cash20_exit_price"], 12.0, places=2)
        self.assertTrue(t["shadow_cash10_exit_at"] < t["shadow_cash20_exit_at"])

    def test_target_not_reached_exits_with_the_real_trade(self):
        t = self.run_prices([10.4, 10.8, 6.9])                              # never +10%, then the real stop (7.0) is hit
        self.assertEqual(t["status"], "CLOSED")
        self.assertEqual(t["shadow_cash15_exit_price"], t["exit_price"])
        self.assertTrue(t.get("shadow_cash15_at_real_exit"))

    def test_review_counts_it(self):
        t = self.run_prices([10.4, 11.2, 11.6, 9.0, 6.9])                   # +16% peak, then stopped out: cash15 would have sold at 11.5
        d = tr._shadow_deltas(t, float(t["exit_price"]))
        self.assertGreater(d["d_cash15"], 0)
        self.assertEqual(d["hit_cash15"], 1)
        self.assertEqual(d["hit_cash20"], 0)


if __name__ == "__main__":
    unittest.main()
