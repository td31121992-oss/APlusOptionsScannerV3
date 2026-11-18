import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"                  # tests must never send alerts

import derived_tags as dt
import paper_trade_journal as pj

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 11, 20, 10, 0, tzinfo=IST)


def closed(side="PE", **kw):
    t = {"entry_time": T0.isoformat(), "exit_time": (T0 + timedelta(minutes=30)).isoformat(), "option_type": side,
         "entry_price": 100.0, "exit_price": 120.0, "quantity": 100, "net_pnl": 1800.0, "gross_pnl": 2000.0}
    t.update(kw)
    return t


class Wait2PutTests(unittest.TestCase):
    def test_registered(self):
        self.assertIn("dx_e_wait2_put", dt.FORWARD_VARIANTS)

    def test_record_opt2_waits_two_minutes_and_needs_two_percent(self):
        t = {"entry_time": T0.isoformat()}
        pj.record_opt2(t, 100.0, 105.0, T0 + timedelta(seconds=90))
        self.assertNotIn("opt2", t)
        pj.record_opt2(t, 100.0, 101.5, T0 + timedelta(seconds=125))
        self.assertEqual(t["opt2"], "FAILED")
        pj.record_opt2(t, 100.0, 110.0, T0 + timedelta(seconds=200))       # set once only
        self.assertEqual(t["opt2"], "FAILED")
        u = {"entry_time": T0.isoformat(), "last_ask": 103.0}
        pj.record_opt2(u, 100.0, 102.5, T0 + timedelta(seconds=130))
        self.assertEqual((u["opt2"], u["opt2_ask"]), ("HELD", 103.0))

    def test_calls_keep_the_real_result(self):
        self.assertEqual(dt.wait2_put_pnl(closed("CE", opt2="FAILED")), 1800.0)

    def test_put_failed_is_not_taken_and_held_is_repriced_at_the_ask(self):
        self.assertEqual(dt.wait2_put_pnl(closed(opt2="FAILED")), 0.0)
        self.assertEqual(dt.wait2_put_pnl(closed(opt2="HELD", opt2_ask=103.0, opt2_price=102.5)), round((120 - 103) * 100 - 200, 2))

    def test_put_over_before_two_minutes_is_not_taken(self):
        t = closed(exit_time=(T0 + timedelta(seconds=70)).isoformat())
        self.assertEqual(dt.wait2_put_pnl(t), 0.0)
        self.assertIsNone(dt.wait2_put_pnl(closed()))                         # lasted 30 min but nothing recorded: cannot tell

    def test_trades_before_the_first_recorded_day_are_unknown(self):
        t = closed(entry_time="2026-11-19T10:00:00+05:30", opt2="FAILED")
        self.assertIsNone(dt.wait2_put_pnl(t))


if __name__ == "__main__":
    unittest.main()
