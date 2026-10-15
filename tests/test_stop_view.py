import unittest

import stop_view as sv


def trade(**kw):
    t = {"entry_price": 10.0, "option_stop": 8.0, "highest_option_price": 10.0, "option_target1": 12.0, "option_target2": 13.5,
         "option_target3": 15.0}
    t.update(kw)
    return t


class StopViewTests(unittest.TestCase):
    def test_initial_stop_and_next_trigger_in_shadow_mode(self):
        s = sv.stop_state(trade(), "SHADOW", "SHADOW")
        self.assertEqual((s["start_sl"], s["cur_sl"], s["sl_label"]), (8.0, 8.0, "Initial"))
        self.assertIn("12.00", s["sl_next"])

    def test_target_locks_move_the_stop(self):
        s = sv.stop_state(trade(target1_hit_at="x"), "SHADOW", "SHADOW")
        self.assertEqual((s["cur_sl"], s["sl_label"]), (10.0, "T1 hit: at cost"))
        s = sv.stop_state(trade(target1_hit_at="x", target2_hit_at="y"), "SHADOW", "SHADOW")
        self.assertEqual(s["cur_sl"], 10.8)
        s = sv.stop_state(trade(target1_hit_at="x", target2_hit_at="y", target3_hit_at="z", highest_option_price=20.0), "SHADOW", "SHADOW")
        self.assertEqual(s["cur_sl"], 17.0)                      # entry + 70% of the 10 point gain
        self.assertTrue(s["sl_label"].startswith("Runner"))

    def test_ladder_mode_follows_the_user_ladder(self):
        s = sv.stop_state(trade(highest_option_price=11.2), "ENFORCE", "SHADOW")          # +12% peak -> lock +3%
        self.assertEqual(s["cur_sl"], 10.3)
        self.assertIn("Ladder +3", s["sl_label"])
        self.assertIn("+20%", s["sl_next"])

    def test_manual_stop_only_tightens(self):
        self.assertEqual(sv.stop_state(trade(manual_stop=9.0), "SHADOW", "SHADOW")["sl_label"], "Manual")
        self.assertEqual(sv.stop_state(trade(manual_stop=7.0), "SHADOW", "SHADOW")["cur_sl"], 8.0)

    def test_missing_fields(self):
        self.assertEqual(sv.stop_state({"entry_price": 0}), {})


if __name__ == "__main__":
    unittest.main()
