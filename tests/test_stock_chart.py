from __future__ import annotations

import unittest

import stock_chart as sc
import trade_chart as tc


def candle(t, o, h, l, c):
    return {"t": t, "o": o, "h": h, "l": l, "c": c}


class MarkTests(unittest.TestCase):
    CANDLES = [candle(1_000_000, 100, 101, 99, 100.5), candle(1_000_300, 100.5, 105, 100, 104), candle(1_000_600, 104, 104.5, 97, 98)]

    def test_day_high_and_low_carry_the_time_of_their_candle(self) -> None:
        m = {x["key"]: x for x in sc.marks(self.CANDLES, {"pdh": 103.0, "pdl": 96.0})}
        self.assertEqual((m["dayhigh"]["price"], m["dayhigh"]["time"]), (105, 1_000_300))
        self.assertEqual((m["daylow"]["price"], m["daylow"]["time"]), (97, 1_000_600))
        self.assertEqual((m["pdh"]["price"], m["pdl"]["price"]), (103.0, 96.0))
        self.assertRegex(m["dayhigh"]["hm"], r"^\d\d:\d\d$")

    def test_missing_previous_day_levels_or_candles_are_skipped(self) -> None:
        self.assertEqual([x["key"] for x in sc.marks(self.CANDLES, None)], ["dayhigh", "daylow"])
        self.assertEqual(sc.marks([], {"pdh": 1.0}), [{"key": "pdh", "name": "PDH", "price": 1.0, "time": None, "label": "previous day high"}])

    def test_pages_and_links(self) -> None:
        import aplus_live_pnl_dashboard as dash
        import stock_analysis_tab as sat
        self.assertIn("/api/stock-day-chart", sc.STOCK_CHART_HTML)
        self.assertIn("createPriceLine", sc.STOCK_CHART_HTML)
        self.assertIn("/stock-chart?symbol=", sat.STOCK_ANALYSIS_HTML)
        self.assertIn("stock_marks", tc.TRADE_HTML)
        self.assertIn("id=\"lvchart\"", sat.STOCK_ANALYSIS_HTML)
        self.assertIn("/api/stock-day-chart", sat.STOCK_ANALYSIS_HTML)
        self.assertTrue(callable(dash.stock_chart.payload))


if __name__ == "__main__":
    unittest.main()
