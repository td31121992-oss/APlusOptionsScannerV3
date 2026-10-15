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


class PerStockTests(unittest.TestCase):
    def test_attach_scans_uses_row_prices_and_daily_levels(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "data" / "reports"
            d.mkdir(parents=True)
            (d / "daily_indicators.json").write_text(json.dumps({"symbols": {"AAA": {"ema20": 100.0, "pdh": 101.0, "hi_5d": 103.0}}}))
            rows = [{"symbol": "AAA", "ltp": 104.0, "open_0915": 99.0, "day_high": 104.5, "day_low": 99.0, "previous_close": 99.5},
                    {"symbol": "ZZZ", "ltp": 0}]
            stt.attach_scans(rows, tmp)
            texts = {s["text"] for s in rows[0]["scans"]}
            self.assertIn("20 EMA Breakout 1D", texts)
            self.assertIn("Open = Low", texts)
            self.assertNotIn("scans", rows[1])

    def test_market_watch_and_analysis_pages_carry_the_new_widgets(self):
        import aplus_live_pnl_dashboard as dash
        import stock_analysis_tab as sa
        self.assertIn("Intraday scans", dash.FNO_MARKET_WATCH_HTML)
        self.assertIn("scanflt", dash.FNO_MARKET_WATCH_HTML)
        self.assertIn("/api/stock-trend", sa.STOCK_ANALYSIS_HTML)
        self.assertEqual(dash.FNO_MARKET_WATCH_HTML.count("`") % 2, 0)       # template literals balanced


class ScanTimeTests(unittest.TestCase):
    def test_each_scan_gets_the_time_it_first_happened(self):
        # 5-minute bars from 09:15: (minute, o, h, l, c)
        bars = [(555, 99.0, 99.6, 99.0, 99.4), (560, 99.4, 100.4, 99.3, 100.2), (565, 100.2, 101.6, 100.1, 101.5),
                (570, 101.5, 103.4, 101.4, 103.2), (575, 103.2, 104.5, 103.0, 104.0)]
        ind = {"ema20": 100.0, "pdh": 101.0, "hi_5d": 103.0, "hi_10d": 109.0}
        got = {s["text"]: s.get("time") for s in stt.scans(104.0, 99.0, 104.5, 99.0, 99.5, ind, True, bars)}
        self.assertEqual(got["20 EMA Breakout 1D"], "09:20")          # first bar whose high went above 100
        self.assertEqual(got["Above yesterday's high"], "09:25")      # high 101.6 > 101.0
        self.assertEqual(got["5 Days Breakout"], "09:30")             # high 103.4 > 103.0
        self.assertEqual(got["Open = Low"], "09:15")
        self.assertNotIn("10 Days Breakout", got)

    def test_build_passes_minutes_through(self):
        n = 40
        five = {"o": [100 + 0.1 * i for i in range(n)], "h": [100.3 + 0.1 * i for i in range(n)], "l": [99.8 + 0.1 * i for i in range(n)],
                "c": [100.2 + 0.1 * i for i in range(n)], "v": [1000.0] * n, "m": [555 + 5 * i for i in range(n)]}
        out = stt.build(five, 0, None, {"pdh": 101.0}, 99.9)
        hit = [s for s in out.get("scans", []) if s["text"] == "Above yesterday's high"]
        self.assertTrue(hit and hit[0].get("time", "").count(":") == 1)


class TickTimeTests(unittest.TestCase):
    def test_market_watch_scans_get_times_from_the_order_book_file(self):
        import json
        import tempfile
        from datetime import date
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "reports").mkdir(parents=True)
            (root / "data" / "order_book").mkdir(parents=True)
            (root / "data" / "reports" / "daily_indicators.json").write_text(json.dumps({"symbols": {"AAA": {"pdh": 101.0, "hi_5d": 103.0}}}))
            today = date.today().isoformat()
            lines = ["time,symbol,ltp,volume"]
            for m, px in ((555, 99.2), (560, 100.5), (565, 101.4), (570, 103.5), (575, 104.0)):
                lines.append(f"{today}T{m // 60:02d}:{m % 60:02d}:20+05:30,AAA,{px},1000")
            (root / "data" / "order_book" / f"{today}.csv").write_text("\n".join(lines))
            stt._TICKS.update({"mtime": 0.0, "at": 0.0, "day": "", "data": {}})
            rows = [{"symbol": "AAA", "ltp": 104.0, "open_0915": 99.0, "day_high": 104.0, "day_low": 99.0, "previous_close": 99.5}]
            stt.attach_scans(rows, root)
            got = {s["text"]: s.get("time") for s in rows[0]["scans"]}
            self.assertEqual(got["Above yesterday's high"], "09:25")
            self.assertEqual(got["5 Days Breakout"], "09:30")
            self.assertEqual(got["Open = Low"], "09:15")
