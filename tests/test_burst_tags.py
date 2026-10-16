import unittest

import burst_tags as bt


def bar(o, c, v):
    return {"open": o, "high": max(o, c), "low": min(o, c), "close": c, "volume": v}


class BurstTests(unittest.TestCase):
    def test_ratio_and_alignment(self):
        bars = [bar(100, 100.5, 1000), bar(100.5, 101, 1000), bar(101, 103, 5000), bar(103, 103.1, 1000), bar(103.1, 103.2, 1000), bar(103.2, 103.1, 2000)]
        t = bt.burst_tags(bars, "BULLISH")
        self.assertEqual(t["bu_max_x"], 5.0)                      # median volume is 1000
        self.assertEqual(t["bu_max_ago"], 3)
        self.assertTrue(t["bu_max_aligned"])
        self.assertEqual(t["bu_last_x"], 2.0)
        self.assertEqual(t["bu_n3"], 1)
        self.assertFalse(bt.burst_tags(bars, "BEARISH")["bu_max_aligned"])

    def test_too_few_bars_or_no_volume(self):
        self.assertEqual(bt.burst_tags([bar(1, 2, 10)] * 3, "BULLISH"), {})
        self.assertEqual(bt.burst_tags([bar(1, 2, 0)] * 6, "BULLISH"), {})
        self.assertEqual(bt.burst_tags(None, "BULLISH"), {})


if __name__ == "__main__":
    unittest.main()
