import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"                  # tests must never send alerts

import derived_tags
import paper_trade_journal as pj
from paper_trade_journal import PaperTradeJournal

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 11, 19, 10, 0, tzinfo=IST)


def record(high, price, seconds=1800):
    trade = {"entry_time": T0.isoformat(), "entry_price": 100.0, "quantity": 100}
    journal = PaperTradeJournal.__new__(PaperTradeJournal)
    journal._record_stop_shadows(trade, 100.0, high, price, T0 + timedelta(seconds=seconds))
    return trade


class LateTrailShadowTests(unittest.TestCase):
    def test_registered_everywhere(self):
        self.assertIn("lt40", pj.STOP_SHADOW_NAMES)
        self.assertIn("dx_x_lt40", derived_tags.SHADOW_EXIT_VARIANTS)
        self.assertIn("dx_x_lt40", derived_tags.FORWARD_VARIANTS)

    def test_fires_when_the_gain_falls_to_sixty_percent_of_the_best(self):
        t = record(high=150.0, price=129.0)          # floor = 100 + 0.6 * 50 = 130
        self.assertEqual(t["shadow_lt40_exit_price"], 129.0)
        self.assertEqual(t["shadow_lt40_floor"], 130.0)

    def test_does_not_fire_above_the_floor_or_before_it_is_armed(self):
        self.assertNotIn("shadow_lt40_exit_price", record(high=150.0, price=131.0))
        self.assertNotIn("shadow_lt40_exit_price", record(high=139.0, price=110.0))   # never up 40%

    def test_unfired_rule_equals_the_real_result_and_fired_uses_its_price(self):
        t = {"entry_time": "2026-11-20T10:00:00+05:30", "entry_price": 100.0, "quantity": 100, "net_pnl": 500.0, "gross_pnl": 700.0}
        self.assertEqual(derived_tags.shadow_exit_variants(t)["dx_x_lt40"], 500.0)
        t["shadow_lt40_exit_price"] = 130.0
        self.assertEqual(derived_tags.shadow_exit_variants(t)["dx_x_lt40"], 2800.0)


if __name__ == "__main__":
    unittest.main()
