import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import paper_trade_journal as pj
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")


def T(m, s=0):
    return datetime(2026, 10, 14, 10, m, s, tzinfo=IST)


def run(prices, mode):
    with mock.patch.dict(os.environ, {"APLUS_EXIT_LADDER_MODE": mode}):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-14", [_open_trade(entry_time="2026-10-14T10:00:00+05:30", option_stop=8.0, option_target1=12.0, option_target2=13.5, option_target3=15.0)])
            for i, p in enumerate(prices):
                j.update_open_positions(option_quotes={"123": {"last_price": p}}, when=T(1, i))
            return dict(j.trades[0])


class OldRulesShadowTests(unittest.TestCase):
    def test_registered(self):
        self.assertIn("old_rules", pj.STOP_SHADOW_NAMES)

    def test_floor_copies_the_live_rules(self):
        trade = {"option_stop": 8.0, "option_target1": 12.0}
        f = pj.PaperTradeJournal._stop_shadow_floors
        self.assertEqual(f(trade, 10.0, 11.0)["old_rules"], 8.0)                                            # no target yet: the initial stop
        self.assertEqual(f({**trade, "target1_hit_at": "x"}, 10.0, 12.1)["old_rules"], 10.0)                # T1 -> entry
        self.assertAlmostEqual(f({**trade, "target1_hit_at": "x", "target2_hit_at": "x"}, 10.0, 13.6)["old_rules"], 10.8)   # T2 -> +8%
        self.assertAlmostEqual(f({**trade, "target1_hit_at": "x", "target2_hit_at": "x", "target3_hit_at": "x"}, 10.0, 15.1)["old_rules"], 13.57)   # T3: 70% of the gain beats the +15% floor

    def test_old_rules_keep_being_measured_when_the_ladder_is_enforced(self):
        path = [15.1, 14.0, 13.5, 12.9]
        real = run(path, "ENFORCE")                                                                          # the ladder floor at a +51% peak is +30% = 13.0: out at 12.9
        self.assertEqual((real["status"], real["exit_price"]), ("CLOSED", 12.9))
        self.assertEqual(real["shadow_old_rules_exit_price"], 13.5)                                          # the old runner trail (13.57) would have been out earlier, at 13.5
        self.assertNotIn("shadow_old_rules_at_real_exit", real)
        old = run(path, "SHADOW")                                                                            # in shadow mode the old rules ARE the real exit
        self.assertEqual((old["exit_price"], old["exit_reason"]), (13.5, "RUNNER_TRAIL_EXIT"))
        self.assertEqual((old["shadow_user_ladder_exit_price"], old["shadow_user_ladder_at_real_exit"]), (13.5, True))   # the ladder (floor 13.0) had not triggered when the real trade closed: it ends with it


if __name__ == "__main__":
    unittest.main()
