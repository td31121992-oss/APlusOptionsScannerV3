import unittest

from shadow_1m_batch_evaluation import summarize_sessions


def session(day, files, valid, outcomes, damaged=0):
    labels = [
        {"symbol": f"S{i}", "confirmed": True, "forward_best_pct": best, "forward_worst_pct": worst}
        for i, (best, worst) in enumerate(outcomes)
    ]
    confirmed = len(labels)
    eligible = confirmed * 2
    return {
        "manifest": {"stocks": {"files": files, "damaged_files": damaged, "invalid_rows": 0},
                     "options": {"damaged_files": 0, "invalid_rows": 0}},
        "report": {
            "day": day,
            "counts": {"symbols_with_valid_opening_range": valid, "candidates": eligible,
                       "eligible_candidates": eligible, "confirmed": confirmed},
            "summary": {"confirmation_rate_pct": 50.0, "median_directional_best_pct": 0.2,
                        "median_directional_worst_pct": -0.2, "count_best_at_least_1pct": 0,
                        "count_worst_at_or_below_minus_1pct": 0},
            "candidate_labels": labels,
        },
    }


class ShadowOneMinuteBatchTests(unittest.TestCase):
    def test_pools_only_full_coverage_clean_sessions_and_pools_raw_outcomes(self):
        broad = session("2026-10-28", 210, 205, [(0.4, -0.2), (1.2, -1.1)])
        partial = session("2026-10-27", 20, 20, [(5.0, -5.0)])
        damaged = session("2026-10-26", 210, 210, [(3.0, -3.0)], damaged=210)
        report = summarize_sessions([partial, damaged, broad])
        pooled = report["clean_broad_coverage_pooled"]
        self.assertEqual(pooled["days"], ["2026-10-28"])
        self.assertEqual(pooled["eligible_candidates"], 4)
        self.assertEqual(pooled["confirmed"], 2)
        self.assertEqual(pooled["median_directional_best_pct"], 0.8)
        by_day = {row["day"]: row for row in report["sessions"]}
        self.assertFalse(by_day["2026-10-27"]["broad_coverage_session"])
        self.assertTrue(by_day["2026-10-28"]["clean_broad_coverage_session"])
        self.assertTrue(by_day["2026-10-26"]["broad_coverage_session"])
        self.assertFalse(by_day["2026-10-26"]["clean_broad_coverage_session"])


if __name__ == "__main__":
    unittest.main()
