import unittest

import numpy as np

import baseline_replay as br

M = [9 * 60 + 15 + 5 * i for i in range(30)]          # 30 five-minute bars from 09:15


def bars(opens, highs, lows, closes):
    n = len(opens)
    return M[:n], opens, highs, lows, closes


class EngineTests(unittest.TestCase):
    def test_initial_stop_and_costs(self):
        # signal at bar 0; fill = open of bar 1 (100) + 1 % = 101; the stop is 80 % of that = 80.8; bar 2 trades down to 78
        m, o, h, lo, c = bars([100, 100, 95, 90], [101, 101, 96, 91], [99, 99, 78, 89], [100, 100, 80, 90])
        r = br.simulate(m, o, h, lo, c, 0)
        self.assertEqual(r["why"], "STOP")
        self.assertAlmostEqual(r["entry"], 101.0)
        self.assertAlmostEqual(r["exit"], 80.8 * 0.99)
        self.assertAlmostEqual(r["net_rs"], br.STAKE_RS * (80.8 * 0.99 / 101.0 - 1) - br.COST_RS)

    def test_gap_through_the_stop_fills_at_the_open(self):
        m, o, h, lo, c = bars([100, 100, 100, 60], [101, 101, 101, 62], [99, 99, 99, 58], [100, 100, 100, 59])
        r = br.simulate(m, o, h, lo, c, 0)
        self.assertEqual(r["why"], "STOP")
        self.assertAlmostEqual(r["exit"], 60 * 0.99)

    def test_ladder_lock_after_a_run(self):
        # entry 101; bar 2 reaches 125 (+23.8 %): lock +13 % = 114.1; bar 3 falls to 110 and is stopped there
        m, o, h, lo, c = bars([100, 100, 110, 118, 112], [101, 101, 125, 119, 113], [99, 99, 109, 110, 111], [100, 100, 120, 112, 112])
        r = br.simulate(m, o, h, lo, c, 0)
        self.assertEqual(r["why"], "LOCK")
        self.assertAlmostEqual(r["exit"], min(118, 101 * 1.13) * 0.99, places=2)

    def test_session_end_and_no_bar(self):
        m, o, h, lo, c = bars([100, 100, 101, 102], [101, 101, 103, 104], [99, 99, 100, 101], [100, 100, 102, 103])
        r = br.simulate(m, o, h, lo, c, 0)
        self.assertEqual(r["why"], "SESSION_END")
        self.assertAlmostEqual(r["exit"], 103 * 0.99)
        self.assertIsNone(br.simulate(m, o, h, lo, c, 3))

    def test_peak_is_reported(self):
        m, o, h, lo, c = bars([100, 100, 150], [101, 101, 205], [99, 99, 149], [100, 100, 200])
        self.assertGreater(br.simulate(m, o, h, lo, c, 0)["peak_pct"], 100)


class TriggerTests(unittest.TestCase):
    def test_breakout_and_control(self):
        minutes = np.array([9 * 60 + 15 + 5 * i for i in range(40)])
        spot = np.array([100.0] * 6 + [100.2 + 0.1 * i for i in range(34)])         # drifts up to ~103.5
        t = br.triggers(minutes, spot)
        self.assertEqual(t["BREAKOUT"][1], 1)
        self.assertEqual(t["CONTROL"][1], 1)
        self.assertGreaterEqual(minutes[t["BREAKOUT"][0]], 9 * 60 + 30)

    def test_down_move_gives_puts(self):
        minutes = np.array([9 * 60 + 15 + 5 * i for i in range(40)])
        spot = np.array([100.0] * 6 + [99.8 - 0.1 * i for i in range(34)])
        self.assertEqual(br.triggers(minutes, spot)["BREAKOUT"][1], -1)

    def test_bullish_order_block_retest(self):
        # base 100, rises to 102 (>1.2 %), pulls back into the block (100.1), then ticks up
        minutes = np.array([9 * 60 + 15 + 5 * i for i in range(40)])
        spot = np.array([101.0, 100.8, 100.5, 100.2, 100.0, 100.1, 100.6, 101.2, 101.8, 102.0, 101.7, 101.2, 100.6, 100.1, 100.15] + [100.2] * 25)
        self.assertTrue(br._ob_retest(spot, 14, 1))
        self.assertFalse(br._ob_retest(spot, 14, -1))

    def test_no_retest_when_the_block_is_broken(self):
        spot = np.array([101.0, 100.8, 100.5, 100.2, 100.0, 100.1, 100.6, 101.2, 101.8, 102.0, 101.7, 101.0, 100.0, 99.2, 99.4] + [99.5] * 25)
        self.assertFalse(br._ob_retest(spot, 14, 1))                    # price went through the bottom of the zone

    def test_bearish_order_block_retest(self):
        # a local high of 100, a fall to 98 (2 %), a return up into the block (99.9), then a tick down
        spot = np.array([99.0, 99.2, 99.5, 99.8, 100.0, 99.9, 99.4, 98.8, 98.2, 98.0, 98.3, 98.8, 99.4, 99.9, 99.85] + [99.8] * 25)
        self.assertTrue(br._ob_retest(spot, 14, -1))
        self.assertFalse(br._ob_retest(spot, 14, 1))

    def test_flat_day_has_no_trigger(self):
        minutes = np.array([9 * 60 + 15 + 5 * i for i in range(40)])
        self.assertEqual(br.triggers(minutes, np.full(40, 100.0)), {})


if __name__ == "__main__":
    unittest.main()
