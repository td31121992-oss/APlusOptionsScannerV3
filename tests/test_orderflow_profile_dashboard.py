import unittest
from unittest.mock import patch

import orderflow_profile_dashboard


class OrderFlowDashboardTests(unittest.TestCase):
    def test_payload_uses_read_only_profile_and_discloses_footprint_gap(self):
        candles = [
            {"t": 1, "o": 100, "h": 102, "l": 99, "c": 101, "v": 100},
            {"t": 2, "o": 101, "h": 103, "l": 100, "c": 102, "v": 200},
        ]
        with patch("trade_chart._UNIVERSE", {"TEST": 123}), patch("trade_chart._candles", return_value=candles):
            result = orderflow_profile_dashboard.payload("TEST", "2026-10-27")
        self.assertTrue(result["ok"])
        self.assertEqual(result["analysis_mode"], "READ_ONLY")
        self.assertFalse(result["volume_profile"]["is_true_trade_at_price_profile"])
        self.assertFalse(result["footprint"]["ok"])
        self.assertEqual(result["footprint"]["reason"], "bid_ask_volume_by_price_unavailable")

    def test_invalid_symbol_does_not_call_market_data(self):
        with patch("trade_chart._candles") as candles:
            result = orderflow_profile_dashboard.payload("../bad", "2026-10-27")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_symbol")
        candles.assert_not_called()


if __name__ == "__main__":
    unittest.main()
