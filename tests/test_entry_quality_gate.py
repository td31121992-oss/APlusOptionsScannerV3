import unittest
from unittest import mock

import entry_quality_gate


class EntryQualityGateTests(unittest.TestCase):
    def _candidate(self, **overrides):
        row = {
            "direction": "BULLISH",
            "selection_score": 89.52,
            "movement_capture_score": 70.31,
            "trend_alignment_score": 89.17,
            "clean_trend_score": 96.25,
            "chase_risk_score": 0.0,
            "recent_move_15m_percent": 1.129,
            "selection_tier": "TREND_MONITOR",
            "rule_reasons": "TOO_EARLY|AGAINST_INDEX",
            "day_regime": "CHOP",
        }
        row.update(overrides)
        return row

    def test_tcs_like_strong_stock_can_pass_despite_early_time_or_index_conflict(self):
        result = entry_quality_gate.evaluate(self._candidate(), {"nifty_pct_open": -0.2})
        self.assertEqual(result["quality_gate_verdict"], "PASS")
        self.assertTrue(result["quality_gate_index_conflict_context"])
        self.assertEqual(result["quality_gate_mode"], "SHADOW_ONLY")

    def test_weak_alignment_and_no_directional_momentum_are_flagged(self):
        result = entry_quality_gate.evaluate(self._candidate(
            direction="BEARISH",
            selection_score=64.75,
            trend_alignment_score=54.5,
            clean_trend_score=87.48,
            chase_risk_score=15,
            recent_move_15m_percent=0.0,
        ))
        self.assertEqual(result["quality_gate_verdict"], "WOULD_BLOCK")
        self.assertIn("SELECTION_SCORE_BELOW_MIN", result["quality_gate_reasons"])
        self.assertIn("DIRECTIONAL_15M_MOMENTUM_WEAK", result["quality_gate_reasons"])

    def test_high_scoring_but_fading_or_chased_setup_is_flagged(self):
        result = entry_quality_gate.evaluate(self._candidate(
            selection_score=85.31,
            movement_capture_score=73.7,
            trend_alignment_score=84.83,
            clean_trend_score=97.57,
            chase_risk_score=15,
            recent_move_15m_percent=0.388,
            opt_late_guard20=True,
        ))
        self.assertEqual(result["quality_gate_verdict"], "WOULD_BLOCK")
        self.assertIn("CHASE_RISK_HIGH", result["quality_gate_reasons"])
        self.assertIn("OPTION_LATE_ENTRY_GUARD", result["quality_gate_reasons"])

    def test_bearish_direction_uses_inverted_stock_momentum(self):
        row = self._candidate(
            direction="BEARISH",
            recent_move_15m_percent=-0.819,
            selection_score=69.97,
            chase_risk_score=15,
        )
        result = entry_quality_gate.evaluate(row)
        self.assertAlmostEqual(result["quality_gate_directional_15m_pct"], 0.819)
        self.assertEqual(result["quality_gate_verdict"], "WOULD_BLOCK")

    def test_thresholds_are_configurable_for_replay(self):
        with mock.patch.dict("os.environ", {"APLUS_QUALITY_MIN_SELECTION_SCORE": "90"}):
            result = entry_quality_gate.evaluate(self._candidate())
        self.assertEqual(result["quality_gate_verdict"], "WOULD_BLOCK")


if __name__ == "__main__":
    unittest.main()
