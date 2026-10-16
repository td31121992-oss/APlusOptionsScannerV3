import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS

import break_tags as bt

IST = timezone(timedelta(hours=5, minutes=30))


def bar(h, m, c):
    return NS(timestamp=datetime(2026, 10, 16, h, m, tzinfo=IST), open=c, high=c, low=c, close=c)


class BreakTagTests(unittest.TestCase):
    def test_call_breaks_r1_during_the_day(self):
        cs = [bar(9, 15, 99.0), bar(9, 20, 99.5), bar(9, 25, 100.4), bar(9, 30, 100.9)]
        t = bt.break_tags(cs, "BULLISH", 100.0, 95.0, 101.0, 9 * 60 + 35)
        self.assertEqual(t["pv_break_time"], "09:25")
        self.assertEqual(t["pv_since_break_min"], 10)
        self.assertFalse(t["pv_gap"])
        self.assertAlmostEqual(t["pv_break_dist_pct"], 0.4, places=2)
        self.assertAlmostEqual(t["pv_past_level_pct"], 1.0, places=2)
        self.assertEqual(t["pv_level"], 100.0)

    def test_put_uses_s1_and_gap_is_flagged(self):
        cs = [bar(9, 15, 94.0), bar(9, 20, 93.5), bar(9, 25, 93.0)]
        t = bt.break_tags(cs, "BEARISH", 105.0, 95.0, 93.0, 9 * 60 + 40)
        self.assertEqual(t["pv_break_time"], "09:15")
        self.assertTrue(t["pv_gap"])
        self.assertAlmostEqual(t["pv_past_level_pct"], (1 - 93.0 / 95.0) * 100, places=2)

    def test_no_break_yet(self):
        cs = [bar(9, 15, 99.0), bar(9, 20, 99.4)]
        t = bt.break_tags(cs, "BULLISH", 100.0, 95.0, 99.4, 9 * 60 + 30)
        self.assertEqual(t["pv_break_time"], "")
        self.assertLess(t["pv_past_level_pct"], 0)
        self.assertNotIn("pv_since_break_min", t)

    def test_bad_input(self):
        self.assertEqual(bt.break_tags(None, "BULLISH", 100, 90, 100, 570), {})
        self.assertEqual(bt.break_tags([], "BULLISH", 0, 0, 100, 570), {})


if __name__ == "__main__":
    unittest.main()
