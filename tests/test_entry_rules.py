import os
import unittest
from unittest import mock

import entry_rules as er


class EntryRuleTests(unittest.TestCase):
    def test_pass(self):
        v = er.evaluate("BULLISH", 10 * 60 + 5, 0.3, 1)
        self.assertEqual(v["rule_verdict"], "PASS")
        self.assertEqual(er.evaluate("BEARISH", 11 * 60, -0.2, 0)["rule_verdict"], "PASS")

    def test_each_rule(self):
        self.assertEqual(er.evaluate("BULLISH", 9 * 60 + 40, 0.3, 0)["rule_reasons"], "TOO_EARLY")
        self.assertEqual(er.evaluate("BULLISH", 10 * 60 + 30, -0.1, 0)["rule_reasons"], "AGAINST_INDEX")
        self.assertEqual(er.evaluate("BEARISH", 10 * 60 + 30, 0.4, 0)["rule_reasons"], "AGAINST_INDEX")
        self.assertEqual(er.evaluate("BULLISH", 10 * 60 + 30, 0.4, 3)["rule_reasons"], "SIDE_CAP")
        self.assertEqual(er.evaluate("BULLISH", 9 * 60 + 30, -0.4, 3)["rule_reasons"], "TOO_EARLY|AGAINST_INDEX|SIDE_CAP")

    def test_unknown_index_passes(self):
        self.assertEqual(er.evaluate("BULLISH", 11 * 60, None, 0)["rule_verdict"], "PASS")
        self.assertEqual(er.evaluate("BULLISH", 11 * 60, "", 0)["rule_nifty_pct_open"], "")

    def test_env_and_mode(self):
        with mock.patch.dict(os.environ, {"APLUS_ENTRY_RULES_MODE": "enforce", "APLUS_ENTRY_RULES_START": "09:45",
                                          "APLUS_ENTRY_RULES_MAX_PER_SIDE": "5"}):
            self.assertEqual(er.mode(), "ENFORCE")
            self.assertEqual(er.evaluate("BULLISH", 9 * 60 + 50, 0.2, 4)["rule_verdict"], "PASS")
        with mock.patch.dict(os.environ, {"APLUS_ENTRY_RULES_MODE": "junk"}):
            self.assertEqual(er.mode(), "SHADOW")


if __name__ == "__main__":
    unittest.main()
