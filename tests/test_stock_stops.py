import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS

import paper_trade_journal as pj
import stock_stops as ss

IST = timezone(timedelta(hours=5, minutes=30))


def bar(h, m, o, hi, lo, c):
    return NS(timestamp=datetime(2026, 10, 16, h, m, tzinfo=IST), open=o, high=hi, low=lo, close=c)


def candles():
    return [bar(9, 15, 100, 101, 98, 100.5), bar(9, 20, 100.5, 102, 99, 101.5), bar(9, 25, 101.5, 103, 100, 102.5), bar(9, 30, 102.5, 104, 101.5, 103.5),
            bar(9, 35, 103.5, 105, 102.5, 104.5), bar(9, 40, 104.5, 106, 103.5, 105.5), bar(9, 45, 105.5, 107, 104.0, 106.5)]


class StockStopTests(unittest.TestCase):
    def test_levels_for_calls_and_puts(self):
        c = ss.entry_levels(candles(), "BULLISH")
        self.assertEqual(c["sk_orb_level"], 98.0)                  # lowest low of the 09:15-09:25 bars
        self.assertEqual(c["sk_sw_level"], 99.0)                   # lowest low of the last 6 bars (09:20 onward)
        p = ss.entry_levels(candles(), "BEARISH")
        self.assertEqual(p["sk_orb_level"], 103.0)
        self.assertEqual(p["sk_sw_level"], 107.0)

    def test_breached(self):
        self.assertTrue(ss.breached(97.0, 98.0, "CE"))
        self.assertFalse(ss.breached(99.0, 98.0, "CE"))
        self.assertTrue(ss.breached(108.0, 107.0, "PE"))
        self.assertFalse(ss.breached(0, 98.0, "CE"))

    def test_shadow_needs_two_readings_in_a_row_and_recovers(self):
        t = {"option_type": "CE", "sk_orb_level": 98.0, "sk_sw_level": 101.5}
        when = datetime(2026, 10, 16, 10, 0, tzinfo=IST)
        rec = pj.PaperTradeJournal._record_structure_shadows
        rec(t, 97.5, 30.0, when)
        self.assertNotIn("shadow_skorb_exit_at", t)               # one reading is not enough
        rec(t, 99.0, 31.0, when)                                   # back above the opening-range level resets the count (still under the swing)
        self.assertEqual(t["shadow_skorb_breaches"], 0)
        rec(t, 97.0, 29.0, when)
        rec(t, 96.5, 28.0, when)
        self.assertEqual(t["shadow_skorb_exit_price"], 28.0)
        self.assertEqual(t["shadow_sksw_exit_price"], 31.0)       # swing level 101.5 was already breached on the first two readings (97.5, 99.0)
        rec(t, 90.0, 10.0, when)
        self.assertEqual(t["shadow_skorb_exit_price"], 28.0)      # first trigger stands

    def test_registered(self):
        self.assertIn("skorb", pj.STOP_SHADOW_NAMES)
        self.assertIn("sksw", pj.STOP_SHADOW_NAMES)
        self.assertIn("sk_", pj.SHADOW_TAG_PREFIXES)


if __name__ == "__main__":
    unittest.main()
