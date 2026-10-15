import math
import unittest

import stock_trend as stt


def series(n, start=100.0, step=0.1, wobble=0.15):
    c = [start + step * i + wobble * math.sin(i / 2.0) for i in range(n)]
    o = [c[0]] + c[:-1]
    h = [max(a, b) + 0.1 for a, b in zip(o, c)]
    l = [min(a, b) - 0.1 for a, b in zip(o, c)]
    return o, h, l, c, [1000.0] * n


class IndicatorTests(unittest.TestCase):
    def test_rsi_and_macd_directions(self):
        o, h, l, c, v = series(120, step=0.2)
        self.assertGreater(stt.rsi(c), 60)
        line, sig = stt.macd(c)
        self.assertGreater(line, 0)
        o, h, l, c, v = series(120, step=-0.2)
        self.assertLess(stt.rsi(c), 40)

    def test_adx_and_supertrend_on_a_clean_uptrend(self):
        o, h, l, c, v = series(120, step=0.3, wobble=0.05)
        a, pdi, mdi = stt.adx(h, l, c)
        self.assertGreater(a, 25)
        self.assertGreater(pdi, mdi)
        st, trend = stt.supertrend(h, l, c)
        self.assertEqual(trend, 1)
        self.assertLess(st, c[-1])

    def test_analyse_counts_and_gauge_score(self):
        o, h, l, c, v = series(260, step=0.15, wobble=0.05)
        r = stt.analyse(o, h, l, c, v, 200, "5M")
        self.assertGreater(r["bullish"], r["bearish"])
        self.assertGreater(r["score"], 0.3)
        self.assertTrue({"ADX", "MACD", "RSI", "SuperTrend", "ATR", "VWAP", "20 EMA"} <= {row["name"] for row in r["table"]})

    def test_too_little_data_is_reported_not_crashed(self):
        o, h, l, c, v = series(10)
        self.assertEqual(stt.analyse(o, h, l, c, v, 0, "5M")["table"], [])

    def test_resample_keeps_the_last_bar(self):
        o, h, l, c, v = series(31)
        r = stt.resample(o, h, l, c, v, 3)
        self.assertEqual(len(r[3]), 10)
        self.assertEqual(r[3][-1], c[-1])


class ScanTests(unittest.TestCase):
    def test_breakouts_and_open_low(self):
        ind = {"ema20": 100.0, "dma200": 90.0, "pdh": 101.0, "hi_5d": 103.0, "hi_10d": 109.0, "pdl": 95.0, "lo_5d": 94.0}
        got = {s["text"] for s in stt.scans(104.0, 99.0, 104.5, 99.0, 99.5, ind)}
        self.assertIn("20 EMA Breakout 1D", got)
        self.assertIn("Above yesterday's high", got)
        self.assertIn("5 Days Breakout", got)
        self.assertNotIn("10 Days Breakout", got)
        self.assertIn("Open = Low", got)


if __name__ == "__main__":
    unittest.main()
