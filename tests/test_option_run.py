import unittest
from datetime import datetime, timedelta

import entry_tags as et
import trade_journal as tj

T = datetime(2026, 10, 15, 9, 36, 0)


def candles(closes, lows=None):
    """5-minute candles starting 09:15; epoch seconds like the Dhan response."""
    t0 = datetime(2026, 10, 15, 9, 15)
    ts = [(t0 + timedelta(minutes=5 * i)).timestamp() for i in range(len(closes))]
    return {"timestamp": ts, "close": closes, "low": lows or [c * 0.97 for c in closes], "open": closes, "high": closes, "volume": [1] * len(closes)}


class OptionRunTests(unittest.TestCase):
    def test_extended_option_triggers_the_guard(self):
        # candles closing 09:20 .. 09:30: the option sat near 40 until 09:15 and then ran to 68 by 09:30
        c = candles([37.75, 40.0, 52.0, 61.0])          # 09:15, 09:20, 09:25, 09:30 candle starts; at 09:36 the 09:15 candle (close 37.75) is the one 15 min back
        r = et.option_run(c, 70.0, T)
        self.assertGreaterEqual(r["opt_run15_pct"], 30.0)
        self.assertTrue(r["opt_late_guard30"])
        self.assertTrue(r["opt_late_guard20"])
        self.assertGreater(r["opt_run_from_low_pct"], 80)

    def test_quiet_option_is_not_flagged(self):
        c = candles([50.0, 50.5, 51.0, 51.2, 51.5, 51.6, 51.8])
        r = et.option_run(c, 52.0, datetime(2026, 10, 15, 9, 51))
        self.assertFalse(r["opt_late_guard20"])
        self.assertFalse(r["opt_late_guard30"])
        self.assertLess(abs(r["opt_run15_pct"]), 5)

    def test_not_enough_history_or_bad_input(self):
        self.assertEqual(et.option_run(candles([50.0, 51.0]), 52.0, T), {})
        self.assertEqual(et.option_run({}, 52.0, T), {})
        self.assertEqual(et.option_run(candles([50.0, 51.0, 52.0, 53.0]), 0, T), {})
        self.assertEqual(et.option_run(None, 52.0, T), {})

    def test_journal_text(self):
        t = {"opt_run15_pct": 41.0, "opt_run30_pct": 79.0, "opt_run_from_low_pct": 90.0, "opt_late_guard30": True, "opt_late_guard20": True}
        s = tj._option_run_text(t)
        self.assertIn("+41% in the last 15 min", s)
        self.assertIn("SKIPPED", s)
        self.assertEqual(tj._option_run_text({}), "")
        self.assertIn("stretched", tj._option_run_text({"opt_run15_pct": 22.0, "opt_late_guard30": False, "opt_late_guard20": True}))


if __name__ == "__main__":
    unittest.main()
