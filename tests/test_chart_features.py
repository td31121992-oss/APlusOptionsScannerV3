from __future__ import annotations

import unittest

import chart_features as cf


class FeatureTests(unittest.TestCase):
    UP = [100 + i * 0.2 for i in range(30)]

    def test_directional_flips_with_side(self) -> None:
        up, down = cf.feature_vector(self.UP, 1), cf.feature_vector(self.UP, -1)
        self.assertGreater(up["d_ret_6"], 0)
        self.assertAlmostEqual(up["d_ret_6"], -down["d_ret_6"])
        self.assertAlmostEqual(up["range_pos_dir"], 1.0)
        self.assertAlmostEqual(down["range_pos_dir"], 0.0)

    def test_no_future_data_is_needed_and_short_series_are_safe(self) -> None:
        v = cf.feature_vector([100.0, 100.1, 100.2], 1)
        self.assertEqual(set(v), set(cf.feature_vector(self.UP, 1)))
        self.assertEqual(cf.pct_change([100.0], 3), 0.0)

    def test_straight_line_has_full_efficiency_and_chop_has_little(self) -> None:
        self.assertAlmostEqual(cf.trend_efficiency(self.UP, 12), 1.0)
        chop = [100, 101] * 10
        self.assertLess(cf.trend_efficiency(chop, 12), 0.2)

    def test_opening_range_status(self) -> None:
        s = [100, 100.2, 99.9, 100.1, 100.4, 100.9]
        self.assertEqual(cf.opening_range_status(s, 1), 1.0)           # above the first-3-bar range, bullish
        self.assertEqual(cf.opening_range_status(s, -1), -1.0)         # same move is against a bearish view


if __name__ == "__main__":
    unittest.main()
