import unittest

import market_brake as mb


class BrakeTests(unittest.TestCase):
    def setUp(self):
        mb._hist.clear()

    def test_open_against_blocks_calls_not_puts(self):
        t = mb.brake_tags("BULLISH", -0.4, now=1000.0)
        self.assertEqual((t["mb_nifty_open_dir"], t["mb_would_block"], t["mb_reason"]), (-0.4, 1, "OPEN_AGAINST"))
        p = mb.brake_tags("BEARISH", -0.4, now=1000.0)
        self.assertEqual((p["mb_nifty_open_dir"], p["mb_would_block"]), (0.4, 0))

    def test_trend_needs_an_old_enough_reading(self):
        mb.brake_tags("BULLISH", 0.5, now=1000.0)
        t = mb.brake_tags("BULLISH", 0.35, now=1000.0 + 5 * 60)                       # too recent to count as a 15-minute reading
        self.assertNotIn("mb_nifty_15_dir", t)
        t2 = mb.brake_tags("BULLISH", 0.3, now=1000.0 + 15 * 60)
        self.assertAlmostEqual(t2["mb_nifty_15_dir"], -0.2, places=3)
        self.assertEqual((t2["mb_would_block"], t2["mb_reason"]), (1, "TREND_AGAINST"))

    def test_market_with_us_and_bad_input(self):
        t = mb.brake_tags("BULLISH", 0.6, now=1.0)
        self.assertEqual((t["mb_would_block"], t["mb_reason"]), (0, ""))
        self.assertEqual(mb.brake_tags("BULLISH", "", now=1.0), {})
        self.assertEqual(mb.brake_tags("BULLISH", float("nan"), now=1.0), {})


if __name__ == "__main__":
    unittest.main()
