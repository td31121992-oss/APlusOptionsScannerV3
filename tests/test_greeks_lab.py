import unittest
from unittest import mock

import greeks_lab as gl

SPOT = 100.0


def row(strike, ltp, bid, ask, iv=30.0, status="ELIGIBLE", lot=100):
    return {"strike": strike, "ltp": ltp, "bid": bid, "ask": ask, "iv": iv, "status": status, "itm": strike < SPOT, "lot_size": lot, "from_spot_pct": abs(strike - SPOT) / SPOT * 100.0,
            "spread_pct": round((ask - bid) / ask * 100.0, 2)}


def lab(side="CE", dte=20):
    return {"ok": True, "symbol": "ZZZ", "side": side, "expiry": "2026-11-18", "expiries": ["2026-11-18"], "scanner_expiry": "2026-11-18", "days_to_expiry": dte, "spot": SPOT,
            "atm": 100.0, "chosen": {"strike": 100.0}, "captured_at": "2026-10-28T10:00:00",
            "rows": [row(95.0, 7.3, 7.25, 7.35), row(100.0, 4.0, 3.95, 4.05), row(105.0, 1.9, 1.85, 1.95), row(130.0, 0.05, 0.0, 0.1, status="REJECTED")]}


def run(fn, *a, side="CE", dte=20, **kw):
    with mock.patch.object(gl.contract_lab, "analyse", return_value=lab(side, dte)):
        return fn("ZZZ", side, "", *a, **kw)


class GreeksLabTests(unittest.TestCase):
    def test_table_has_greeks_and_leaves_out_far_strikes(self):
        t = run(gl.table)
        self.assertTrue(t["ok"])
        self.assertEqual([r["strike"] for r in t["rows"]], [95.0, 100.0, 105.0])          # 130 is 30% away
        atm = t["rows"][1]
        self.assertTrue(0.4 < atm["delta"] < 0.65)
        self.assertLess(atm["theta_day"], 0)
        self.assertGreater(atm["gamma"], 0)
        self.assertGreater(atm["vega"], 0)
        self.assertEqual(atm["theta_lot_day"], round(atm["theta_day"] * 100, 0))
        self.assertEqual(t["chosen_strike"], 100.0)
        self.assertAlmostEqual(atm["breakeven_pct"], 4.0, places=2)                         # 100 + 4.00 premium vs spot 100

    def test_put_breakeven_and_delta_sign(self):
        t = run(gl.table, side="PE")
        atm = t["rows"][1]
        self.assertLess(atm["delta"], 0)
        self.assertAlmostEqual(atm["breakeven_pct"], -4.0, places=2)

    def test_a_scenario_with_nothing_changed_gives_back_the_market_price(self):
        w = run(gl.whatif, 100.0, 0, 0, 0)
        self.assertTrue(w["ok"])
        self.assertAlmostEqual(w["new_price"], 4.0, delta=0.01)
        self.assertAlmostEqual(w["pnl_share"], 0.0, delta=0.01)
        self.assertEqual(w["pnl_lot"], 0)

    def test_stock_direction_helps_the_right_side(self):
        up_call = run(gl.whatif, 100.0, 2, 0, 0)["pnl_share"]
        up_put = run(gl.whatif, 100.0, 2, 0, 0, side="PE")["pnl_share"]
        self.assertGreater(up_call, 0)
        self.assertLess(up_put, 0)

    def test_time_and_iv_move_the_price_the_expected_way(self):
        flat_later = run(gl.whatif, 100.0, 0, 5, 0)
        self.assertLess(flat_later["new_price"], 4.0)
        self.assertEqual(flat_later["theta_only_price"], flat_later["new_price"])
        self.assertGreater(run(gl.whatif, 100.0, 0, 0, 5)["new_price"], 4.0)
        self.assertLess(run(gl.whatif, 100.0, 0, 0, -5)["new_price"], 4.0)

    def test_at_expiry_the_option_is_worth_only_its_intrinsic_value(self):
        w = run(gl.whatif, 100.0, 3, 99, 0)                    # days clamp to expiry + half a day
        self.assertEqual(w["inputs"]["days"], 20.5)
        self.assertAlmostEqual(w["new_price"], 3.0, delta=0.01)        # stock 103 vs strike 100
        self.assertAlmostEqual(run(gl.whatif, 100.0, -3, 99, 0)["new_price"], 0.0, delta=0.01)

    def test_grid_and_curve_shapes(self):
        w = run(gl.whatif, 100.0, 0, 0, 0)
        self.assertEqual(len(w["grid"]), len(gl.MOVES))
        self.assertTrue(all(len(g["cells"]) == len(w["grid_days"]) for g in w["grid"]))
        self.assertEqual(w["grid_days"][0], 0.0)
        self.assertEqual(w["grid_days"][-1], 20.5)
        flat = w["curve"]["flat"]
        self.assertTrue(all(a >= b for a, b in zip(flat, flat[1:])))                      # flat stock: premium only melts
        short = run(gl.whatif, 100.0, 0, 0, 0, dte=2)
        self.assertTrue(all(d <= 2.5 for d in short["grid_days"]))

    def test_unknown_strike_and_inputs_outside_range(self):
        self.assertFalse(run(gl.whatif, 777.0, 0, 0, 0)["ok"])
        w = run(gl.whatif, 100.0, 500, -4, 999)
        self.assertEqual((w["inputs"]["move"], w["inputs"]["days"], w["inputs"]["iv"]), (30.0, 0.0, 30.0))
        self.assertTrue(gl.whatif.__doc__)

    def test_lab_errors_pass_through(self):
        with mock.patch.object(gl.contract_lab, "analyse", return_value={"ok": False, "error": "no expiry"}):
            self.assertEqual(gl.table("ZZZ")["error"], "no expiry")
            self.assertEqual(gl.whatif("ZZZ", "CE", "", 100)["error"], "no expiry")

    def test_page_text(self):
        self.assertIn("Greeks Lab", gl.GREEKS_LAB_HTML)
        self.assertIn("/api/greeks-whatif", gl.GREEKS_LAB_HTML)


if __name__ == "__main__":
    unittest.main()
