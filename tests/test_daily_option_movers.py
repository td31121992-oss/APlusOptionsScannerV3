import unittest
from datetime import date

import daily_movers_telegram as dm


def r(sym, typ, prev, ltp, vol=100000, lot=100, stock=1.0, strike=100.0):
    return {"symbol": sym, "type": typ, "prev": prev, "ltp": ltp, "volume": vol, "lot": lot, "stock_pct": stock, "strike": strike}


class OptionMoverTests(unittest.TestCase):
    def test_ranking_filters_and_best_strike_per_stock(self):
        rows = [r("AAA", "CE", 10, 25), r("AAA", "CE", 5, 8),                     # best AAA call strike is +150%
                r("BBB", "CE", 2.0, 20),                                           # prev close under Rs 3: ignored
                r("CCC", "CE", 20, 30, vol=500),                                   # 5 lots only: ignored
                r("DDD", "CE", 30, 33), r("EEE", "CE", 40, 40),                    # +10% and unchanged
                r("FFF", "PE", 12, 30), r("GGG", "PE", 50, 40)]                    # a gainer and a loser
        calls, puts = dm.rank_option_movers(rows)
        self.assertEqual([c["symbol"] for c in calls], ["AAA", "DDD"])
        self.assertAlmostEqual(calls[0]["pct"], 150.0)
        self.assertEqual([p["symbol"] for p in puts], ["FFF"])

    def test_message_has_both_sections(self):
        calls, puts = dm.rank_option_movers([r("AAA", "CE", 10, 25, strike=1330.0), r("FFF", "PE", 12, 30, strike=870.0)])
        text = dm.format_message(date(2026, 10, 15), [], [], 213, calls, puts)
        self.assertIn("TOP 5 CALL PREMIUM GAINERS", text)
        self.assertIn("AAA 1330 CE", text)
        self.assertIn("TOP 5 PUT PREMIUM GAINERS", text)
        self.assertIn("FFF 870 PE", text)
        self.assertIn("(+150%)", text)

    def test_card_renders(self):
        import tempfile
        from pathlib import Path
        calls, puts = dm.rank_option_movers([r("AAA", "CE", 10, 25, strike=1330.0), r("FFF", "PE", 12, 30, strike=870.0)])
        with tempfile.TemporaryDirectory() as tmp:
            p = dm.render_options_card(date(2026, 10, 15), calls, puts, Path(tmp) / "x.png")
            self.assertTrue(p.exists() and p.stat().st_size > 5000)


if __name__ == "__main__":
    unittest.main()
