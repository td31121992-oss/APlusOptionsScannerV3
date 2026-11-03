import unittest

import paper_trade_journal as ptj

J = ptj.PaperTradeJournal


class BigPeakFloorTests(unittest.TestCase):
    def test_floor_only_after_the_rupee_peak(self):
        trade = {"quantity": 1000, "option_stop": 8.0}
        low = J._stop_shadow_floors(trade, 10.0, 12.0)          # peak profit Rs 2,000: below every threshold
        self.assertEqual(low["bigpeak25_r3000"], 0.0)
        self.assertEqual(low["bigpeak30_r4000"], 0.0)
        hi = J._stop_shadow_floors(trade, 10.0, 15.0)           # peak profit Rs 5,000
        self.assertAlmostEqual(hi["bigpeak25_r4000"], 10.0 + 5.0 * 0.75)
        self.assertAlmostEqual(hi["bigpeak30_r3000"], 10.0 + 5.0 * 0.70)

    def test_names_are_recorded_like_the_other_shadows(self):
        for name in ptj.BIGPEAK_NAMES:
            self.assertIn(name, ptj.STOP_SHADOW_NAMES)
        self.assertEqual(ptj.BIGPEAK_NAMES, ("bigpeak25_r3000", "bigpeak30_r3000", "bigpeak25_r4000", "bigpeak30_r4000"))

    def test_no_quantity_means_no_floor(self):
        self.assertEqual(J._stop_shadow_floors({"option_stop": 8.0}, 10.0, 20.0)["bigpeak25_r3000"], 0.0)


if __name__ == "__main__":
    unittest.main()
