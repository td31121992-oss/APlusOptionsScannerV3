import unittest

from scripts.offline_breakout_robustness import build_report, summarize


def row(symbol, day, split, value, variant="baseline", horizon=15, interval=5, overlap=True):
    return {
        "symbol": symbol, "interval_minutes": str(interval), "session_date": day,
        "split": split, "side": "SHORT_BREAKDOWN", "filter_variant": variant,
        "horizon_bars": str(horizon), "outcome_available": "True",
        "non_overlapping": str(overlap), "directional_return_pct": str(value),
        "mfe_pct": "0.2", "mae_pct": "-0.1",
        "signal_timestamp": day + "T09:30:00+05:30",
        "entry_timestamp": day + "T09:30:00+05:30",
        "exit_timestamp": day + "T10:45:00+05:30",
    }


class OfflineBreakoutRobustnessTests(unittest.TestCase):
    def test_summary_exposes_winner_concentration(self):
        result = summarize([
            {"directional_return_pct": "1", "mfe_pct": "1.1", "mae_pct": "-0.2"},
            {"directional_return_pct": "0.5", "mfe_pct": "0.8", "mae_pct": "-0.3"},
            {"directional_return_pct": "-0.25", "mfe_pct": "0.2", "mae_pct": "-0.5"},
        ])
        self.assertEqual(result["n"], 3)
        self.assertAlmostEqual(result["top_1_winner_share_of_positive_returns_pct"], 66.67, places=2)

    def test_train_test_and_symbol_concentration_are_separated(self):
        rows = [
            row("AAA", "2026-10-01", "train", 0.2),
            row("AAA", "2026-10-20", "test", 0.4),
            row("BBB", "2026-10-20", "test", -0.1),
        ]
        report = build_report(rows)
        candidate = next(item for item in report["candidate_results"]
                         if item["interval_minutes"] == 5 and item["filter_variant"] == "baseline")
        self.assertEqual(candidate["train"]["n"], 1)
        self.assertEqual(candidate["test"]["n"], 2)
        self.assertEqual(candidate["test_symbols"], 2)
        self.assertEqual(candidate["symbols_positive_mean"], 1)
        self.assertEqual(report["timestamp_audit"]["invalid_signal_entry_exit_order_count"], 0)

    def test_timestamp_audit_flags_mixed_timezone_formats(self):
        rows = [row("AAA", "2026-10-01", "test", 0.1)]
        rows[0]["signal_timestamp"] = "2026-10-01T09:30:00"
        report = build_report(rows)
        self.assertTrue(report["timestamp_audit"]["mixed_naive_and_offset_aware"])


if __name__ == "__main__":
    unittest.main()
