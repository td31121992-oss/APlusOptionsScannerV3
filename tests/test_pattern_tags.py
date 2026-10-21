import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pattern_tags as pt

IST = timezone(timedelta(hours=5, minutes=30))


def candles(rows):
    """rows = (open, high, low, close); 5-minute bars from 09:15."""
    base = datetime(2026, 10, 21, 9, 15, tzinfo=IST)
    return [NS(timestamp=base + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c, volume=1000) for i, (o, h, l, c) in enumerate(rows)]


UP = [(100, 101, 99.8, 100.8), (100.8, 101.6, 100.6, 101.4), (101.4, 102.2, 101.2, 102.0), (102.0, 102.8, 101.8, 102.6)]


class PatternTagTests(unittest.TestCase):
    def test_bearish_engulfing_after_a_run_is_against_a_call(self):
        rows = UP + [(102.6, 103.0, 102.5, 102.9), (103.1, 103.2, 101.9, 102.0)]       # last bar swallows the previous green one
        t = pt.pattern_tags(candles(rows), "BULLISH")
        self.assertIn("bearish_engulfing:against", t["pt_recent"])
        self.assertTrue(t["pt_reversal_against"])
        self.assertGreaterEqual(t["pt_against"], 1)
        self.assertIn("bearish_engulfing:against", t["pt_last_bar"])

    def test_same_tape_is_with_a_put(self):
        rows = UP + [(102.6, 103.0, 102.5, 102.9), (103.1, 103.2, 101.9, 102.0)]
        t = pt.pattern_tags(candles(rows), "BEARISH")
        self.assertIn("bearish_engulfing:with", t["pt_recent"])
        self.assertFalse(t["pt_reversal_against"])

    def test_old_patterns_drop_out_of_the_recent_window(self):
        rows = [(100, 101, 99.8, 100.8), (100.8, 101.0, 99.5, 99.7), (99.6, 101.5, 99.4, 101.3)] + [(101.3, 101.5, 101.2, 101.4)] * 7   # engulfing on bar 3, quiet after
        t = pt.pattern_tags(candles(rows), "BULLISH")
        self.assertNotIn("bullish_engulfing", t["pt_recent"])

    def test_too_few_candles_and_bad_input(self):
        self.assertEqual(pt.pattern_tags(candles(UP[:3]), "BULLISH"), {})
        self.assertEqual(pt.pattern_tags(None, "BULLISH"), {})


if __name__ == "__main__":
    unittest.main()
