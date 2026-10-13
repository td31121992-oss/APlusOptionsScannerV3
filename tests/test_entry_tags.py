import unittest
from datetime import datetime

import entry_tags as et


class EntryTagTests(unittest.TestCase):
    def test_flags(self):
        t = et.evaluate(12.5, datetime(2026, 10, 14, 10, 5), "chop")
        self.assertTrue(t["f_time_0945"] and t["f_premium_5"] and t["f_all"])
        self.assertEqual(t["day_regime"], "CHOP")
        e = et.evaluate(4.0, datetime(2026, 10, 14, 9, 30))
        self.assertFalse(e["f_time_0945"] or e["f_premium_5"] or e["f_all"])
        self.assertEqual(e["day_regime"], "UNKNOWN")
        self.assertEqual(et.evaluate("x", datetime(2026, 10, 14, 9, 45))["entry_premium"], 0.0)

    def test_regime_of(self):
        self.assertEqual(et.regime_of({"regime": "bull"}), "BULL")
        self.assertEqual(et.regime_of(None), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
