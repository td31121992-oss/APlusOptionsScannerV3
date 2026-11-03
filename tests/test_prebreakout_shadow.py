import unittest

import prebreakout_shadow as shadow


class PrebreakoutShadowTests(unittest.TestCase):
    def bars(self):
        return {
            "minute": [555, 560, 565, 570, 575, 580],
            "open": [100, 100, 102, 104, 104.7, 105.2],
            "high": [101, 103, 105, 104.8, 105.4, 106],
            "low": [99, 100, 101, 103.9, 104.5, 104.8],
            "close": [100, 102, 104, 104.7, 105.2, 105.8],
            "volume": [100, 100, 100, 150, 160, 170],
            "pdh": 106,
            "pdl": 98,
        }

    def test_marks_candidate_before_opening_range_break(self):
        result = shadow.candidates_for_day({"AAA": self.bars()})
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]["symbol"], result[0]["side"], result[0]["minute"]), ("AAA", "BULLISH", 570))
        self.assertLess(result[0]["close"], result[0]["level"])
        self.assertGreaterEqual(result[0]["volume_multiple"], 1.3)

    def test_later_confirmation_is_evaluated_separately(self):
        bars = self.bars()
        candidate = shadow.candidates_for_day({"AAA": bars})[0]
        result = shadow.evaluate_candidate(candidate, bars)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["confirmation_minute"], 575)
        self.assertGreater(result["forward_best_pct"], 0)

    def test_no_volume_or_already_broken_level_is_not_a_candidate(self):
        bars = self.bars()
        bars["volume"][3] = 100
        self.assertEqual(shadow.candidates_for_day({"AAA": bars}), [])

    def test_strict_mode_requires_three_positive_prior_volume_bars(self):
        bars = self.bars()
        bars["volume"][1] = 0
        self.assertEqual(len(shadow.candidates_for_day({"AAA": bars})), 1)
        self.assertEqual(shadow.candidates_for_day({"AAA": bars}, require_complete_volume_window=True), [])
        bars = self.bars()
        bars["high"][3] = 105.1
        bars["close"][3] = 105.0
        self.assertEqual(shadow.candidates_for_day({"AAA": bars}), [])


if __name__ == "__main__":
    unittest.main()
