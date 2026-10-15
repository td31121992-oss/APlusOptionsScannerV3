import unittest

import trade_chart as tc


def candle(t, h, l):
    return {"t": t, "o": l, "h": h, "l": l, "c": h}


class TradeExtremeTests(unittest.TestCase):
    def test_high_since_entry_with_time(self):
        base = 1_760_000_000 - (1_760_000_000 % 300)
        cs = [candle(base + 300 * i, h, h - 1) for i, h in enumerate([50, 12, 14, 20, 18, 16])]
        entry = base + 300 * 1 + 40                           # inside the second candle
        r = tc.trade_extreme(cs, entry, 0, True)
        self.assertEqual(r["price"], 20)                      # the 50 before entry is ignored
        self.assertEqual(r["time"], base + 300 * 3)
        self.assertRegex(r["hm"], r"^\d\d:\d\d$")

    def test_exit_bounds_the_search_and_low_mode(self):
        base = 1_760_000_000 - (1_760_000_000 % 300)
        cs = [candle(base + 300 * i, h, h - 1) for i, h in enumerate([10, 12, 14, 30, 11])]
        r = tc.trade_extreme(cs, base, base + 300 * 2, True)
        self.assertEqual(r["price"], 14)                      # the 30 came after the exit
        low = tc.trade_extreme(cs, base, 0, False)
        self.assertEqual(low["price"], 9)

    def test_no_candles(self):
        self.assertIsNone(tc.trade_extreme([], 100, 0))


if __name__ == "__main__":
    unittest.main()
