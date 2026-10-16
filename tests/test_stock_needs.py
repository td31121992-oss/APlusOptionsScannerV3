import unittest

import stop_view as sv


class StockNeedsTests(unittest.TestCase):
    def test_uses_the_contract_delta_when_known(self):
        t = {"entry_price": 50.0, "underlying_entry": 2000.0, "gk_delta": 0.6, "option_type": "CE"}      # elasticity = 0.6 * 2000 / 50 = 24
        n = sv.stock_needs(t)
        self.assertEqual(n["needs_src"], "delta")
        self.assertEqual(n["needs_el"], 24.0)
        self.assertEqual(n["need10"], round(10 / 24, 2))
        self.assertEqual(n["need30"], round(30 / 24, 2))
        self.assertAlmostEqual(n["need20_px"], 2000 * (1 + (20 / 24) / 100), places=2)

    def test_put_levels_are_below_entry(self):
        t = {"entry_price": 50.0, "underlying_entry": 2000.0, "gk_delta": -0.6, "option_type": "PE"}
        n = sv.stock_needs(t)
        self.assertLess(n["need10_px"], 2000.0)
        self.assertAlmostEqual(n["need10_px"], 2000 * (1 - (10 / 24) / 100), places=2)

    def test_falls_back_to_the_typical_value(self):
        n = sv.stock_needs({"entry_price": 50.0, "underlying_entry": 2000.0, "option_type": "CE"})
        self.assertEqual((n["needs_src"], n["needs_el"]), ("typical", 24.0))
        silly = sv.stock_needs({"entry_price": 1.0, "underlying_entry": 2000.0, "gk_delta": 0.5, "option_type": "CE"})        # elasticity 1000: not believable
        self.assertEqual(silly["needs_src"], "typical")

    def test_missing_prices(self):
        self.assertEqual(sv.stock_needs({}), {})
        self.assertEqual(sv.stock_needs({"entry_price": 50.0}), {})

    def test_pages_show_the_line(self):
        import aplus_live_pnl_dashboard as d
        import positions_panel as pp
        for source in (open(d.__file__, encoding="utf-8").read(), open(pp.__file__, encoding="utf-8").read()):
            self.assertIn("need10", source)
            self.assertIn("for option +10 / 20 / 30%", source)


if __name__ == "__main__":
    unittest.main()
