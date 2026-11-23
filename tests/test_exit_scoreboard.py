import unittest

import pandas as pd

import exit_scoreboard as es


def ticks(rows):
    df = pd.DataFrame(rows, columns=["hms", "ltp", "bid"])
    return df


TRADE = {"entry_price": 100.0, "option_stop": 80.0, "entry_time": "2026-11-20T10:00:00+05:30", "option_target1": 120.0, "option_target2": 135.0, "option_target3": 150.0}


class ReplayTests(unittest.TestCase):
    def test_stop_fills_at_the_bid_of_the_tick_that_crossed_it(self):
        df = ticks([("10:00:05", 100, 99.5), ("10:01:00", 112, 111), ("10:02:00", 102.5, 101.0), ("10:03:00", 130, 129)])
        bid, ltp, how = es.replay(TRADE, df, "ladder2")        # +12% peak locks +3%: the 102.5 tick crosses 103
        self.assertEqual((bid, ltp, how), (101.0, 102.5, "stop"))

    def test_nothing_before_the_entry_and_close_at_the_end(self):
        df = ticks([("09:59:00", 50, 49), ("10:00:30", 101, 100.5), ("15:26:00", 10, 9)])
        bid, ltp, how = es.replay(TRADE, df, "ladder2")
        self.assertEqual((bid, how), (100.5, "end"))

    def test_old_rules_use_the_trades_own_targets(self):
        df = ticks([("10:01:00", 121, 120), ("10:02:00", 99, 98)])      # T1 hit: stop at cost 100
        bid, ltp, how = es.replay(TRADE, df, "old_rules")
        self.assertEqual((bid, how), (98.0, "stop"))


if __name__ == "__main__":
    unittest.main()
