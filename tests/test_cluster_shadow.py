import unittest

import cluster_shadow as cs


def ticks_at(minute, spec):
    """spec: list of (price, qty, side) repeated into the candle."""
    return [(minute, p, q, s) for p, q, s in spec]


class ClusterTests(unittest.TestCase):
    def test_stacked_buy_imbalance_for_a_long(self):
        # prices climb 100.00 .. 100.50 in 0.10 steps; at every step buyers hit the ask three times harder than sellers one step below
        spec = []
        for i in range(6):
            p = 100.0 + 0.10 * i
            spec += [(p, 300, "B")] * 4 + [(p - 0.10, 60, "S")] * 1
        r = cs.cluster(ticks_at(570, spec), 570, 1, 100.1)
        self.assertGreaterEqual(r["stack"], 3)
        self.assertGreater(r["beyond"], 0.5)
        self.assertGreater(r["beyond_imb"], 0.3)

    def test_balanced_flow_has_no_stack(self):
        spec = []
        for i in range(8):
            p = 100.0 + 0.10 * i
            spec += [(p, 100, "B"), (p, 100, "S"), (p - 0.1, 100, "S")]
        r = cs.cluster(ticks_at(570, spec), 570, 1, 100.3)
        self.assertLessEqual(r["stack"], 1)

    def test_short_mirrors_the_long(self):
        spec = []
        for i in range(6):
            p = 100.0 - 0.10 * i
            spec += [(p, 300, "S")] * 4 + [(p + 0.10, 60, "B")] * 1
        r = cs.cluster(ticks_at(570, spec), 570, -1, 99.9)
        self.assertGreaterEqual(r["stack"], 3)
        self.assertGreater(r["beyond_imb"], 0.3)

    def test_too_few_ticks_or_other_candle(self):
        self.assertIsNone(cs.cluster(ticks_at(570, [(100.0, 10, "B")] * 5), 570, 1, 100.0))
        spec = [(100.0 + 0.1 * (i % 5), 10, "B") for i in range(40)]
        self.assertIsNone(cs.cluster(ticks_at(575, spec), 570, 1, 100.0))              # the ticks belong to the next candle


class ReviewTests(unittest.TestCase):
    def test_review_splits_by_stack(self):
        rows = [{"day": "2026-10-26", "time": "09:30", "stack": 0, "poc": 0.5, "beyond_imb": 0.1, "net_rs": -300, "peak_pct": 0, "gross_pct": -5},
                {"day": "2026-10-26", "time": "09:35", "stack": 3, "poc": 0.9, "beyond_imb": 0.4, "net_rs": 900, "peak_pct": 50, "gross_pct": 12}]
        text = cs.review(rows)
        self.assertIn("Stacked imbalances", text)
        self.assertIn("| 0 - 1 | 1 |", text)
        self.assertIn("| 3 or more | 1 |", text)


if __name__ == "__main__":
    unittest.main()
