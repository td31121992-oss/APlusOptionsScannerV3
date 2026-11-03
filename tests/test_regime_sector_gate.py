import unittest

import regime_sector_gate as rsg


def rows(spec):
    out = []
    for sector, moves in spec.items():
        for i, m in enumerate(moves):
            out.append({"symbol": f"{sector[:2]}{i}", "sector": sector, "from_prev_close_pct": m})
    return out


class RegimeSectorTests(unittest.TestCase):
    def setUp(self):
        self.rows = rows({"Banks": [1.0, 0.8, 0.9, 1.2, 0.7], "IT": [-0.2, 0.1, 0.05, -0.1, 0.2], "Metals": [0.5, 0.4, 0.6, 0.3, 0.2], "Pharma": [-0.5, -0.6, -0.4, -0.3, -0.2]})

    def test_call_in_top_sector_with_up_majority_passes(self):
        t = rsg.evaluate("Ba0", "BULLISH", self.rows)
        self.assertEqual((t["rgs_regime"], t["rgs_regime_ok"], t["rgs_top_sector"], t["rgs_sector1_ok"], t["rgs_would_block"]), ("UP", True, "Banks", True, False))

    def test_call_in_other_sector_is_blocked_by_the_sector_part_only(self):
        t = rsg.evaluate("Me0", "BULLISH", self.rows)
        self.assertEqual((t["rgs_sector_rank"], t["rgs_sector1_ok"], t["rgs_sector2_ok"], t["rgs_would_block"], t["rgs_regime_block"]), (2, False, True, True, False))

    def test_put_against_an_up_market_is_blocked_by_the_regime(self):
        t = rsg.evaluate("Ph0", "BEARISH", self.rows)
        self.assertEqual((t["rgs_top_sector"], t["rgs_sector1_ok"], t["rgs_regime_ok"], t["rgs_regime_block"], t["rgs_would_block"]), ("Pharma", True, False, True, True))

    def test_regime60_and_unknown(self):
        t = rsg.evaluate("Ba0", "BULLISH", self.rows)
        self.assertEqual(t["rgs_regime60_ok"], t["rgs_up_pct"] > 60.0)
        self.assertEqual(rsg.evaluate("X", "BULLISH", [])["rgs_regime"], "UNKNOWN")
        self.assertEqual(rsg.evaluate("X", "BULLISH", [{"symbol": "a", "sector": "s", "from_prev_close_pct": "bad"}] * 30), {"rgs_regime": "UNKNOWN"})

    def test_small_sector_ignored_and_unknown_stock_has_no_sector_verdict(self):
        small = rows({"Tiny": [9.0, 9.0], "Banks": [1.0, 0.8, 0.9, 1.2, 0.7], "IT": [0.1, 0.2, 0.1, 0.0, 0.3], "Metals": [0.5, 0.4, 0.6, 0.3, 0.2], "Pharma": [0.1, 0.2, 0.3, 0.1, 0.1]})
        self.assertEqual(rsg.evaluate("Ba0", "BULLISH", small)["rgs_top_sector"], "Banks")          # Tiny has under 4 stocks
        t = rsg.evaluate("NOPE", "BULLISH", small)
        self.assertNotIn("rgs_would_block", t)
        self.assertTrue(t["rgs_regime_ok"])


if __name__ == "__main__":
    unittest.main()
