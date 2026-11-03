from __future__ import annotations

import unittest

import market_mood as mm


def rows(ups, downs, chg=1.0):
    return [{"from_prev_close_pct": chg} for _ in range(ups)] + [{"from_prev_close_pct": -chg} for _ in range(downs)]


class MoodTests(unittest.TestCase):
    def test_bearish_day_scores_low_and_bullish_day_high(self) -> None:
        bear = mm.compute({"nifty_pct_prev": -1.0, "banknifty_pct_prev": -1.2, "vix": 15, "vix_pct_prev": 6}, rows(40, 170), -0.2)
        bull = mm.compute({"nifty_pct_prev": 1.0, "banknifty_pct_prev": 1.2, "vix": 12, "vix_pct_prev": -6}, rows(170, 40), 0.2)
        self.assertLess(bear["score"], 25)
        self.assertGreater(bull["score"], 75)
        self.assertIn(bear["label"], {"Very bearish", "Bearish"})
        self.assertIn(bull["label"], {"Bullish", "Very bullish"})

    def test_flat_market_is_neutral(self) -> None:
        d = mm.compute({"nifty_pct_prev": 0.0, "banknifty_pct_prev": 0.0, "vix": 14, "vix_pct_prev": 0.0}, rows(100, 100, 0.0), 0.0)
        self.assertEqual(d["label"], "Neutral")
        self.assertAlmostEqual(sum(p["weight"] for p in d["parts"]), 100, delta=2)

    def test_missing_parts_are_skipped_and_no_data_is_handled(self) -> None:
        d = mm.compute(None, rows(10, 10), None)
        self.assertEqual([p["key"] for p in d["parts"]], ["breadth", "median"])
        self.assertFalse(mm.compute(None, [], None)["ok"])

    def test_widget_and_pages(self) -> None:
        import aplus_live_pnl_dashboard as dash
        self.assertIn("/api/market-mood", mm.MOOD_WIDGET_HTML)
        page = dash._mobileize_html("<html><head></head><body>x</body></html>")
        self.assertIn('id="aplus-mood"', page)


if __name__ == "__main__":
    unittest.main()
