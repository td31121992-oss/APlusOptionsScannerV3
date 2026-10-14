import unittest
from stock_option_response_shadow import evaluate_response

class ResponseTests(unittest.TestCase):
    def test_call_stock_plus_1_5_option_plus_12(self):
        r = evaluate_response(
            {"paper_trade_id":"T1","side":"CE","underlying_entry_price":1000,
             "option_entry_price":100,"entry_time":"2026-10-13T10:00:00+05:30",
             "day_reference_price":980},
            1015,112,"2026-10-13T10:30:00+05:30")
        self.assertAlmostEqual(r["underlying_move_from_entry_pct"], 1.5)
        self.assertAlmostEqual(r["option_change_from_entry_pct"], 12.0)
        self.assertAlmostEqual(r["stock_move_from_day_reference_at_entry_pct"], 2.0408163265)
        self.assertEqual(r["shadow_mode"], "SHADOW_ONLY")
        self.assertTrue(r["milestones"])

    def test_put_favorable_direction_is_down(self):
        r = evaluate_response(
            {"side":"PE","underlying_entry_price":1000,"option_entry_price":100,
             "entry_time":"2026-10-13T10:00:00+00:00"},
            985,110,"2026-10-13T10:20:00+00:00")
        self.assertAlmostEqual(r["favorable_underlying_move_pct"], 1.5)
        self.assertEqual(r["verdict"], "FAVORABLE_MOVE_OPTION_RESPONDED_SHADOW")

    def test_underlying_favorable_but_option_down(self):
        r = evaluate_response(
            {"side":"CE","underlying_entry_price":1000,"option_entry_price":100},
            1010,96,"2026-10-13T10:20:00+00:00")
        self.assertEqual(r["verdict"], "FAVORABLE_STOCK_WEAK_OPTION_RESPONSE_SHADOW")

    def test_missing_data_safe(self):
        r = evaluate_response({"side":"CE"}, 100, 10)
        self.assertEqual(r["verdict"], "INSUFFICIENT_DATA_SHADOW")
        self.assertEqual(r["shadow_mode"], "SHADOW_ONLY")

if __name__ == "__main__":
    unittest.main()
