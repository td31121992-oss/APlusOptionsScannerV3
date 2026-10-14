import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import entry_tags as et
import trade_journal as tj


def candle(t0, i, o, h, l, c, v=1000):
    return SimpleNamespace(timestamp=t0 + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c, volume=v)


T0 = datetime(2026, 10, 14, 9, 15)


class EntryContextTests(unittest.TestCase):
    def rising(self):
        # a call: steady climb from 100 to 103 over 8 candles, high set by the last candle
        closes = [100.4, 100.8, 101.2, 101.6, 102.0, 102.4, 102.7, 103.0]
        return [candle(T0, i, c - 0.4, c + 0.1, c - 0.5, c) for i, c in enumerate(closes)]

    def test_call_at_the_high_is_flagged(self):
        r = et.entry_context(self.rising(), "BULLISH")
        self.assertGreater(r["ctx_done_move_pct"], 2.5)
        self.assertGreaterEqual(r["ctx_range_pos"], 0.9)
        self.assertTrue(r["ctx_at_extreme"])
        self.assertFalse(r["ctx_fading"])                       # still progressing over the last 15 minutes
        self.assertGreater(r["ctx_last15_pct"], 0)

    def test_fading_after_a_big_move(self):
        cs = self.rising() + [candle(T0, 8, 103.0, 103.05, 102.4, 102.6), candle(T0, 9, 102.6, 102.7, 102.2, 102.3)]
        r = et.entry_context(cs, "BULLISH")
        self.assertGreaterEqual(r["ctx_done_move_pct"], 2.0)
        self.assertLessEqual(r["ctx_last15_pct"], 0)
        self.assertTrue(r["ctx_fading"])

    def test_put_uses_the_low(self):
        closes = [99.6, 99.2, 98.8, 98.4, 98.0, 97.6, 97.3, 97.0]
        cs = [candle(T0, i, c + 0.4, c + 0.5, c - 0.1, c) for i, c in enumerate(closes)]
        r = et.entry_context(cs, "BEARISH")
        self.assertGreater(r["ctx_done_move_pct"], 2.5)
        self.assertGreaterEqual(r["ctx_range_pos"], 0.9)
        # the same candles are the WRONG way round for a call
        self.assertLess(et.entry_context(cs, "BULLISH")["ctx_done_move_pct"], 0)

    def test_not_at_extreme_when_far_from_it_and_long_ago(self):
        cs = [candle(T0, i, 100 + i * 0.3, 100.2 + i * 0.3 + (0.2 if i == 2 else 0), 99.9 + i * 0.3, 100.1 + i * 0.3) for i in range(12)]
        cs[2] = candle(T0, 2, 100.6, 104.0, 100.5, 100.7)        # an early spike sets the high, price drifted well below it
        r = et.entry_context(cs, "BULLISH")
        self.assertFalse(r["ctx_at_extreme"])
        self.assertGreater(r["ctx_mins_since_ext"], 30)

    def test_too_little_data_and_bad_input_return_empty(self):
        self.assertEqual(et.entry_context([], "BULLISH"), {})
        self.assertEqual(et.entry_context(self.rising()[:2], "BULLISH"), {})
        self.assertEqual(et.entry_context(None, "BULLISH"), {})

    def test_journal_text(self):
        t = {"ctx_done_move_pct": 5.85, "ctx_range_pos": 0.83, "ctx_mins_since_ext": 84, "ctx_last15_pct": -0.48,
             "ctx_last30_pct": -0.48, "ctx_vs_vwap_pct": 0.49, "ctx_at_extreme": False, "ctx_fading": True}
        text = tj._context_text(t)
        self.assertIn("+5.85% from the open", text)
        self.assertIn("FADING", text)
        self.assertNotIn("AT THE EXTREME", text)
        self.assertEqual(tj._context_text({}), "")


if __name__ == "__main__":
    unittest.main()
