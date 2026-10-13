import unittest
from datetime import datetime, timedelta, timezone
from option_decay_shadow import evaluate_decay_shadow

class OptionDecayShadowTests(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)
        self.trade = {"paper_trade_id":"PT-TEST","entry_time":self.t0.isoformat(),
                      "underlying_entry":100.0,"entry_price":10.0,
                      "shadow_underlying_peak":100.0,
                      "shadow_underlying_peak_at":self.t0.isoformat(),
                      "shadow_option_peak":10.0,
                      "shadow_option_peak_at":self.t0.isoformat()}

    def test_stall_and_drawdown_flags_decay_risk(self):
        trade = dict(self.trade, shadow_underlying_peak=103.0,
                     shadow_underlying_peak_at=self.t0.isoformat())
        r = evaluate_decay_shadow(trade, underlying_price=102.8, option_price=9.4,
                                  when=self.t0+timedelta(minutes=65))
        self.assertEqual(r["shadow_exit_planner_verdict"], "DECAY_RISK_SHADOW")
        self.assertEqual(r["shadow_exit_planner_mode"], "SHADOW_ONLY")

    def test_strong_stall_is_still_shadow_only(self):
        trade = dict(self.trade, shadow_underlying_peak=103.0,
                     shadow_underlying_peak_at=self.t0.isoformat())
        r = evaluate_decay_shadow(trade, underlying_price=102.8, option_price=9.1,
                                  when=self.t0+timedelta(minutes=95))
        self.assertEqual(r["shadow_exit_planner_verdict"], "EXIT_CANDIDATE_SHADOW")

    def test_no_signal_without_underlying_move(self):
        r = evaluate_decay_shadow(self.trade, underlying_price=100.2, option_price=9.0,
                                  when=self.t0+timedelta(minutes=100))
        self.assertEqual(r["shadow_exit_planner_verdict"], "NO_DECAY_EXIT_SIGNAL_SHADOW")

    def test_missing_data_is_safe(self):
        r = evaluate_decay_shadow(self.trade, underlying_price=None, option_price=9.0, when=self.t0)
        self.assertEqual(r["shadow_exit_planner_verdict"], "INSUFFICIENT_DATA_SHADOW")

if __name__ == "__main__":
    unittest.main()
