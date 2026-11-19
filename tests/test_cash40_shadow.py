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


def record(high, price):
    trade = {"entry_time": T0.isoformat(), "entry_price": 100.0, "quantity": 100}
    journal = PaperTradeJournal.__new__(PaperTradeJournal)
    journal._record_stop_shadows(trade, 100.0, high, price, T0 + timedelta(seconds=1800))
    return trade


class Cash40ShadowTests(unittest.TestCase):
    def test_registered_everywhere(self):
        self.assertIn("cash40", pj.STOP_SHADOW_NAMES)
        self.assertIn("dx_x_cash40", derived_tags.SHADOW_EXIT_VARIANTS)
        self.assertIn("dx_x_cash40", derived_tags.FORWARD_VARIANTS)

    def test_sells_at_exactly_plus_40_when_first_reached(self):
        t = record(high=141.0, price=141.0)
        self.assertEqual(t["shadow_cash40_exit_price"], 140.0)

    def test_does_not_fire_below_plus_40(self):
        self.assertNotIn("shadow_cash40_exit_price", record(high=139.0, price=139.0))

    def test_unfired_equals_real_and_fired_uses_the_target(self):
        t = {"entry_time": "2026-11-20T10:00:00+05:30", "entry_price": 100.0, "quantity": 100, "net_pnl": 500.0, "gross_pnl": 700.0}
        self.assertEqual(derived_tags.shadow_exit_variants(t)["dx_x_cash40"], 500.0)
        t["shadow_cash40_exit_price"] = 140.0
        self.assertEqual(derived_tags.shadow_exit_variants(t)["dx_x_cash40"], 3800.0)


if __name__ == "__main__":
    unittest.main()
