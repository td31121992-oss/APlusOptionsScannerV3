import unittest
from smc_readonly import analyze_smc


class SMCReadOnlyTests(unittest.TestCase):
    def test_insufficient_candles_is_explicit(self):
        self.assertFalse(analyze_smc([{"open": 1, "high": 2, "low": 0, "close": 1}])["ok"])

    def test_read_only_contract_and_score_range(self):
        candles = []
        price = 100.0
        for i in range(40):
            # A gently rising series with periodic pullbacks creates confirmed pivots.
            drift = 1.0 if i % 5 in (0, 1, 2) else -0.25
            o = price
            c = price + drift
            candles.append({"open": o, "high": max(o, c) + 0.4, "low": min(o, c) - 0.4, "close": c, "volume": 1000})
            price = c
        result = analyze_smc(candles)
        self.assertTrue(result["ok"])
        self.assertEqual(result["analysis_mode"], "READ_ONLY")
        self.assertIsNone(result["trade_decision"])
        self.assertIn(result["structure"], {"NEUTRAL", "BULLISH_HH_HL", "BEARISH_LH_LL", "MIXED_BULLISH", "MIXED_BEARISH"})
        self.assertGreaterEqual(result["smc_score"]["bullish"], 0)
        self.assertLessEqual(result["smc_score"]["bullish"], 100)
        self.assertGreaterEqual(result["smc_score"]["bearish"], 0)
        self.assertLessEqual(result["smc_score"]["bearish"], 100)

    def test_invalid_candle_is_ignored(self):
        result = analyze_smc([
            {"open": 1, "high": 2, "low": 0, "close": 1},
            {"open": 3, "high": 1, "low": 2, "close": 3},
        ] * 5)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
