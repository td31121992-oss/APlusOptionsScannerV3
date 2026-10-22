import os
import unittest
from unittest import mock

import quality_gate as qg

GOOD = {"rrg_aligned": True, "chase_risk_score": 0, "ctx_range_pos": 0.8, "tr_htf_n": 4, "tk_delta5_dir": 0.2, "mb_would_block": 0}


class ScoreTests(unittest.TestCase):
    def test_full_marks_and_each_point(self):
        self.assertEqual(qg.score(GOOD), (7, []))
        for key, bad, lost in (("rrg_aligned", False, 2), ("chase_risk_score", 15, 1), ("ctx_range_pos", 0.95, 1), ("tr_htf_n", 2, 1), ("tk_delta5_dir", -0.1, 1), ("mb_would_block", 1, 1)):
            self.assertEqual(qg.score({**GOOD, key: bad})[0], 7 - lost, key)

    def test_missing_tags_earn_nothing_and_are_listed(self):
        sc, missing = qg.score({"rrg_aligned": "True", "chase_risk_score": 0})
        self.assertEqual(sc, 3)
        self.assertEqual(missing, ["range", "htf", "tape", "market"])

    def test_string_booleans_from_the_csv_history(self):
        self.assertEqual(qg.score({**GOOD, "rrg_aligned": "False"})[0], 5)
        self.assertEqual(qg.score({**GOOD, "rrg_aligned": ""})[1][0], "rrg")


class PassTests(unittest.TestCase):
    def test_pass_needs_score_rrg_and_room_in_the_daily_budget(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("APLUS_QUALITY_MIN_SCORE", "APLUS_QUALITY_MAX_PER_DAY", "APLUS_QUALITY_REQUIRE_RRG"):
                os.environ.pop(k, None)
            self.assertEqual(qg.evaluate(GOOD, 0), {"q_score": 7, "q_pass": 1, "q_missing": "", "q_rank_today": 1})
            self.assertEqual(qg.evaluate({**GOOD, "tr_htf_n": 1, "tk_delta5_dir": -1}, 0)["q_pass"], 0)       # score 5 < 6
            self.assertEqual(qg.evaluate({**GOOD, "rrg_aligned": False}, 0)["q_pass"], 0)                      # rrg is required even with 5 other points
            self.assertEqual(qg.evaluate(GOOD, 6)["q_pass"], 0)                                                 # the 7th passing trade of the day is refused
            self.assertEqual(qg.evaluate(GOOD, 5)["q_rank_today"], 6)

    def test_env_switches_and_mode(self):
        with mock.patch.dict(os.environ, {"APLUS_QUALITY_MIN_SCORE": "4", "APLUS_QUALITY_REQUIRE_RRG": "0", "APLUS_QUALITY_MAX_PER_DAY": "2", "APLUS_QUALITY_GATE_MODE": "enforce"}):
            self.assertEqual(qg.mode(), "ENFORCE")
            self.assertEqual(qg.evaluate({"chase_risk_score": 0, "ctx_range_pos": 0.5, "tr_htf_n": 4, "mb_would_block": 0}, 1)["q_pass"], 1)
            self.assertEqual(qg.evaluate(GOOD, 2)["q_pass"], 0)
        with mock.patch.dict(os.environ, {"APLUS_QUALITY_GATE_MODE": "nonsense"}):
            self.assertEqual(qg.mode(), "SHADOW")

    def test_counting_todays_passing_trades(self):
        trades = [{"entry_time": "2026-10-23T09:40:00", "q_pass": 1}, {"entry_time": "2026-10-23T09:50:00", "q_pass": 0}, {"entry_time": "2026-10-22T09:50:00", "q_pass": 1},
                  {"entry_time": "2026-10-23T10:10:00", "q_pass": "True"}]
        self.assertEqual(qg.passes_so_far(trades, "2026-10-23"), 2)


if __name__ == "__main__":
    unittest.main()
