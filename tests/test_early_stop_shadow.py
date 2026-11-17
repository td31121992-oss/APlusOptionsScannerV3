import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"                  # tests must never send alerts

import derived_tags
import paper_trade_journal as pj
from paper_trade_journal import PaperTradeJournal

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 11, 18, 10, 0, tzinfo=IST)


def record(price, seconds):
    trade = {"entry_time": T0.isoformat(), "entry_price": 100.0, "quantity": 100}
    journal = PaperTradeJournal.__new__(PaperTradeJournal)
    journal._record_stop_shadows(trade, 100.0, 100.0, price, T0 + timedelta(seconds=seconds))
    return trade


class EarlyStopShadowTests(unittest.TestCase):
    def test_registered_everywhere(self):
        self.assertIn("early8", pj.STOP_SHADOW_NAMES)
        self.assertIn("dx_x_early8", derived_tags.SHADOW_EXIT_VARIANTS)
        self.assertIn("dx_x_early8", derived_tags.FORWARD_VARIANTS)

    def test_fires_at_minus_8_percent_inside_the_first_five_minutes(self):
        t = record(91.5, 120)
        self.assertEqual(t["shadow_early8_exit_price"], 91.5)

    def test_does_not_fire_above_the_floor_or_after_five_minutes(self):
        self.assertNotIn("shadow_early8_exit_price", record(92.5, 120))      # only -7.5%
        self.assertNotIn("shadow_early8_exit_price", record(90.0, 301))      # window over

    def test_unfired_rule_equals_the_real_result_and_fired_uses_its_price(self):
        t = {"entry_time": "2026-11-18T10:00:00+05:30", "entry_price": 100.0, "quantity": 100, "net_pnl": -3000.0, "gross_pnl": -2800.0}
        self.assertEqual(derived_tags.shadow_exit_variants(t)["dx_x_early8"], -3000.0)
        t["shadow_early8_exit_price"] = 92.0
        self.assertAlmostEqual(derived_tags.shadow_exit_variants(t)["dx_x_early8"], (92.0 - 100.0) * 100 - 200, places=2)
        t["entry_time"] = "2026-11-17T10:00:00+05:30"
        self.assertIsNone(derived_tags.shadow_exit_variants(t)["dx_x_early8"])      # before the rule was recorded


if __name__ == "__main__":
    unittest.main()
