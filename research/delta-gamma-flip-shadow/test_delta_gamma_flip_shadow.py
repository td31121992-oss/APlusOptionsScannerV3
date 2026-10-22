import unittest
from delta_gamma_flip_shadow import black_scholes_greeks, estimate_gamma_flip

class GreeksShadowTests(unittest.TestCase):
    def test_call_and_put_delta_ranges(self):
        call = black_scholes_greeks(spot=100, strike=100, iv=20, time_years=30/365, option_type="CE")
        put = black_scholes_greeks(spot=100, strike=100, iv=0.20, time_years=30/365, option_type="PE")
        self.assertGreater(call["delta"], 0)
        self.assertLess(call["delta"], 1)
        self.assertLess(put["delta"], 0)
        self.assertGreater(call["gamma"], 0)
        self.assertAlmostEqual(call["gamma"], put["gamma"], places=8)

    def test_oi_without_dealer_sign_does_not_claim_flip(self):
        result = estimate_gamma_flip([{"strike":100,"iv":20,"time_years":0.1,"option_type":"CE","open_interest":1000,"lot_size":25}], [90,100,110])
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIsNone(result["flip_level"])
        self.assertIn("dealer_position_sign", result["reason"])

    def test_invalid_dealer_sign_fails_closed(self):
        result = estimate_gamma_flip([{"strike":100,"iv":20,"time_years":0.1,"option_type":"PE","open_interest":1000,"lot_size":25,"dealer_position_sign":0}], [90,100,110])
        self.assertEqual(result["status"], "UNAVAILABLE")

    def test_signed_positions_return_curve(self):
        contracts = [
            {"strike":95,"iv":20,"time_years":0.1,"option_type":"CE","open_interest":1000,"lot_size":25,"dealer_position_sign":1},
            {"strike":105,"iv":20,"time_years":0.1,"option_type":"PE","open_interest":1000,"lot_size":25,"dealer_position_sign":-1},
        ]
        result = estimate_gamma_flip(contracts, range(80,121,2))
        self.assertIn(result["status"], {"ESTIMATED", "NO_CROSSING_IN_GRID"})
        self.assertEqual(result["contract_count"], 2)
        self.assertEqual(len(result["curve"]), 21)

if __name__ == "__main__":
    unittest.main()
