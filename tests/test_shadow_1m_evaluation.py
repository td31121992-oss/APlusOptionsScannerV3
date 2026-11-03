import unittest

from shadow_1m_evaluation import evaluate_rows


class ShadowOneMinuteEvaluationTests(unittest.TestCase):
    def rows(self):
        rows = []
        for i in range(25):
            minute = 9 * 60 + 15 + i
            if i < 3:
                open_price, high, low, close = 99.4, 100.0, 99.2, 99.5
            elif i == 3:
                open_price, high, low, close = 99.5, 99.9, 99.6, 99.85
            elif i == 4:
                open_price, high, low, close = 99.85, 100.3, 99.8, 100.2
            else:
                open_price, high, low, close = 100.2, 100.8, 100.1, 100.6
            rows.append({
                "symbol": "AAA",
                "bar_minute": f"{minute // 60:02d}:{minute % 60:02d}",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume_delta": 150 if i == 3 else 100,
            })
        return rows

    def test_evaluation_is_research_only_and_labels_full_window(self):
        report = evaluate_rows(self.rows(), "2026-10-28")
        self.assertTrue(report["research_only"])
        self.assertTrue(report["not_option_pnl_or_live_strategy_performance"])
        self.assertEqual(report["counts"]["candidates"], 1)
        self.assertEqual(report["counts"]["confirmed"], 1)
        self.assertEqual(report["counts"]["confirmed_with_full_12_bar_outcome"], 1)
        self.assertEqual(report["candidate_labels"][0]["minute"], 558)

    def test_missing_opening_minute_is_excluded(self):
        rows = [row for row in self.rows() if row["bar_minute"] != "09:16"]
        report = evaluate_rows(rows, "2026-10-28")
        self.assertEqual(report["counts"]["symbols_with_valid_opening_range"], 0)
        self.assertEqual(report["counts"]["symbols_excluded_for_missing_or_ambiguous_opening_bars"], 1)

    def test_candidate_with_gapped_forward_window_is_not_filled(self):
        rows = [row for row in self.rows() if row["bar_minute"] != "09:25"]
        report = evaluate_rows(rows, "2026-10-28")
        self.assertEqual(report["counts"]["outcome_ineligible_candidates"], 1)
        self.assertEqual(report["counts"]["eligible_candidates"], 0)


if __name__ == "__main__":
    unittest.main()
