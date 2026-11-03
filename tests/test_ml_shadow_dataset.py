import unittest

from ml_shadow_dataset import build_dataset, chronological_splits


def make_session(day, files=205, valid=205, damaged=0):
    report = {
        "day": day,
        "counts": {"symbols_with_valid_opening_range": valid, "candidates": 1,
                   "eligible_candidates": 1, "confirmed": 1},
        "summary": {"confirmation_rate_pct": 100.0, "median_directional_best_pct": 0.6,
                    "median_directional_worst_pct": -0.2, "count_best_at_least_1pct": 0,
                    "count_worst_at_or_below_minus_1pct": 0},
        "candidate_labels": [{"symbol": "AAA", "side": "BULLISH", "minute": 570,
                              "level_distance_pct": 0.3, "volume_multiple": 1.8,
                              "close_location": 0.85, "confirmed": True,
                              "confirmation_minute": 573, "forward_best_pct": 0.6,
                              "forward_worst_pct": -0.2}],
    }
    manifest = {"stocks": {"files": files, "damaged_files": damaged, "invalid_rows": 0},
                "options": {"damaged_files": 0, "invalid_rows": 0}}
    return {"report": report, "manifest": manifest}


class MLShadowDatasetTests(unittest.TestCase):
    def test_only_clean_broad_sessions_are_included_and_targets_are_separate(self):
        sessions = [make_session("2026-10-22"), make_session("2026-10-28", damaged=205),
                    make_session("2026-10-29", files=20, valid=20)]
        dataset = build_dataset(sessions)
        self.assertEqual(dataset["manifest"]["accepted_sessions"], ["2026-10-22"])
        self.assertEqual(dataset["manifest"]["row_count"], 1)
        self.assertEqual(dataset["manifest"]["splits"]["2026-10-22"], "unassigned_insufficient_sessions")
        row = dataset["rows"][0]
        self.assertEqual(row["confirmed_within_6m"], 1)
        self.assertNotIn("confirmed_within_6m", dataset["manifest"]["feature_columns"])
        self.assertNotIn("symbol", dataset["manifest"]["feature_columns"])
        self.assertFalse(dataset["manifest"]["training_performed"])

    def test_chronological_split_keeps_days_disjoint_and_last_sessions_untouched(self):
        days = [f"2026-10-{day:02d}" for day in range(1, 11)]
        splits = chronological_splits(days)
        self.assertEqual(splits["2026-10-01"], "train")
        self.assertEqual(splits["2026-10-08"], "validation")
        self.assertEqual(splits["2026-10-09"], "untouched_test")
        self.assertEqual(splits["2026-10-10"], "untouched_test")
        self.assertEqual(len(splits), 10)


if __name__ == "__main__":
    unittest.main()
