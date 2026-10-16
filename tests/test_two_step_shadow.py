import unittest

import paper_trade_journal as pj


class TwoStepTests(unittest.TestCase):
    def test_floor_steps(self):
        f = pj.two_step_floor
        self.assertEqual(f(100.0, 104.9), 0.0)                  # not yet +5%
        self.assertAlmostEqual(f(100.0, 105.0), 85.0)           # +5% -> stop -15%
        self.assertAlmostEqual(f(100.0, 109.9), 85.0)
        self.assertEqual(f(100.0, 110.0), 100.0)                # +10% -> cost
        self.assertEqual(f(100.0, 160.0), 100.0)                # nothing further locks
        self.assertEqual(f(0.0, 5.0), 0.0)

    def test_registered_as_a_shadow(self):
        self.assertIn("two_step", pj.STOP_SHADOW_NAMES)
        floors = pj.PaperTradeJournal._stop_shadow_floors({}, 100.0, 112.0)
        self.assertEqual(floors["two_step"], 100.0)
        self.assertAlmostEqual(floors["user_ladder"], 103.0)    # the older ladder is still recorded alongside


if __name__ == "__main__":
    unittest.main()
