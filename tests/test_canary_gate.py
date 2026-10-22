import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import canary_gate as cg

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 22, 10, 20, tzinfo=IST)


def trade(minutes_ago, direction="BEARISH", entry=100.0, high=100.0):
    return {"direction": direction, "entry_time": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "entry_price": entry, "highest_option_price": high}


class CanaryTests(unittest.TestCase):
    def setUp(self):
        for k in list(os.environ):
            if k.startswith("APLUS_CANARY"):
                os.environ.pop(k)

    def test_first_trade_of_a_side_is_allowed(self):
        t = cg.evaluate([trade(2, "BULLISH"), trade(120)], "BEARISH", NOW)                      # other side, and an old same-side trade outside the window
        self.assertEqual((t["cn_ok"], t["cn_reason"], t["cn_recent"]), (1, "FIRST_OF_WINDOW", 0))

    def test_pile_on_is_refused_until_an_earlier_trade_shows_a_gain(self):
        losing = [trade(12, high=101), trade(8, high=100), trade(3, high=100)]
        t = cg.evaluate(losing, "BEARISH", NOW)
        self.assertEqual((t["cn_ok"], t["cn_reason"], t["cn_recent"], t["cn_best_gain_pct"]), (0, "NO_CANARY_PROFIT", 3, 1.0))
        working = losing + [trade(15, high=108)]
        t2 = cg.evaluate(working, "BEARISH", NOW)
        self.assertEqual((t2["cn_ok"], t2["cn_reason"]), (1, "CANARY_OK"))

    def test_the_canary_must_be_old_enough_and_inside_the_window(self):
        self.assertEqual(cg.evaluate([trade(3, high=110)], "BEARISH", NOW)["cn_ok"], 0)         # +10% but only 3 minutes old
        self.assertEqual(cg.evaluate([trade(40, high=130), trade(6, high=100)], "BEARISH", NOW)["cn_ok"], 0)   # the winner is outside the 30-minute window
        with mock.patch.dict(os.environ, {"APLUS_CANARY_MIN_GAIN_PCT": "12", "APLUS_CANARY_WINDOW_MIN": "60"}):
            self.assertEqual(cg.evaluate([trade(40, high=115)], "BEARISH", NOW)["cn_ok"], 1)  # 15% >= 12% and inside the 60-minute window

    def test_the_other_side_does_not_count(self):
        t = cg.evaluate([trade(10, "BULLISH", high=130)], "BEARISH", NOW)
        self.assertEqual((t["cn_ok"], t["cn_reason"]), (1, "FIRST_OF_WINDOW"))

    def test_mode_and_bad_rows(self):
        self.assertEqual(cg.mode(), "SHADOW")
        with mock.patch.dict(os.environ, {"APLUS_CANARY_MODE": "enforce"}):
            self.assertEqual(cg.mode(), "ENFORCE")
        with mock.patch.dict(os.environ, {"APLUS_CANARY_MODE": "nonsense"}):
            self.assertEqual(cg.mode(), "SHADOW")
        bad = [{"direction": "BEARISH", "entry_time": "nonsense"}, {"direction": "BEARISH"}, trade(5, high="x")]
        self.assertEqual(cg.evaluate(bad, "BEARISH", NOW)["cn_ok"], 0)                           # the one valid recent trade has no gain yet


if __name__ == "__main__":
    unittest.main()
