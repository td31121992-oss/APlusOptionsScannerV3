import unittest
from orderflow_profile_readonly import analyze_footprint, build_volume_profile


class ReadOnlyOrderFlowTests(unittest.TestCase):
    def test_profile_marks_ohlcv_method_as_estimate(self):
        result = build_volume_profile([
            {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 100},
            {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 200},
        ], tick_size=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["analysis_mode"], "READ_ONLY")
        self.assertFalse(result["is_true_trade_at_price_profile"])
        self.assertLessEqual(result["val"], result["poc"])
        self.assertLessEqual(result["poc"], result["vah"])

    def test_empty_volume_profile_is_explicit(self):
        self.assertFalse(build_volume_profile([{"low": 1, "high": 2, "close": 1, "volume": 0}])["ok"])

    def test_footprint_refuses_to_invent_bid_ask(self):
        result = analyze_footprint([])
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "bid_ask_volume_by_price_unavailable")

    def test_footprint_delta_and_imbalance(self):
        levels = [
            {"price": 100 + i, "bid_volume": 10, "ask_volume": 40}
            for i in range(3)
        ]
        result = analyze_footprint(levels)
        self.assertTrue(result["ok"])
        self.assertEqual(result["delta"], 90)
        self.assertEqual(len(result["stacked_imbalances"]["buy"]), 1)
        self.assertEqual(result["stacked_imbalances"]["buy"][0]["levels"], 3)
        self.assertEqual(result["analysis_mode"], "READ_ONLY")


if __name__ == "__main__":
    unittest.main()
