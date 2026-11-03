from __future__ import annotations

import os
import unittest

from option_selector import OptionSelector


class MaxLossTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(os.environ.pop, "APLUS_MAX_LOSS_PER_TRADE_RUPEES", None)

    def test_off_by_default_keeps_the_percentage_stop(self) -> None:
        os.environ.pop("APLUS_MAX_LOSS_PER_TRADE_RUPEES", None)
        self.assertEqual(OptionSelector._stop_distance(8.6, 775), 8.6)

    def test_cap_tightens_a_large_position_only(self) -> None:
        os.environ["APLUS_MAX_LOSS_PER_TRADE_RUPEES"] = "3500"
        # MOTILALOFS-sized: 775 units, 30% stop 10.37 would risk ~8,000 -> cap gives ~4.52 (13%)
        self.assertAlmostEqual(OptionSelector._stop_distance(10.37, 775), 3500 / 775)
        # a small position keeps its percentage stop (1000 risk < 3500)
        self.assertEqual(OptionSelector._stop_distance(5.0, 200), 5.0)

    def test_bad_values_fall_back_to_the_percentage_stop(self) -> None:
        os.environ["APLUS_MAX_LOSS_PER_TRADE_RUPEES"] = "abc"
        self.assertEqual(OptionSelector._stop_distance(5.0, 200), 5.0)
        os.environ["APLUS_MAX_LOSS_PER_TRADE_RUPEES"] = "-5"
        self.assertEqual(OptionSelector._stop_distance(5.0, 200), 5.0)


if __name__ == "__main__":
    unittest.main()
