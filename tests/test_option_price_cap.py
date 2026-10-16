import os
import unittest
from unittest import mock

from safety_gate import GateStatus, SafetyGateEngine as SafetyGate


class OptionPriceCapTests(unittest.TestCase):
    def check(self, contract, cap):
        env = {"APLUS_BLOCK_OPTION_PRICE": cap} if cap is not None else {}
        with mock.patch.dict(os.environ, env, clear=False):
            if cap is None:
                os.environ.pop("APLUS_BLOCK_OPTION_PRICE", None)
            return SafetyGate._option_price_check(contract)

    def test_off_by_default(self):
        self.assertEqual(self.check({"limit_price": 500.0}, None).status, GateStatus.PASS)
        self.assertEqual(self.check({"limit_price": 500.0}, "0").status, GateStatus.PASS)
        self.assertEqual(self.check({"limit_price": 500.0}, "junk").status, GateStatus.PASS)

    def test_blocks_at_or_above_the_cap(self):
        self.assertEqual(self.check({"limit_price": 80.0}, "80").status, GateStatus.BLOCK)
        self.assertEqual(self.check({"limit_price": 236.1}, "80").status, GateStatus.BLOCK)
        c = self.check({"limit_price": 79.95}, "80")
        self.assertEqual(c.status, GateStatus.PASS)
        self.assertEqual(c.details["cap"], 80.0)

    def test_falls_back_to_ask_then_ltp(self):
        self.assertEqual(self.check({"ask": 90.0}, "80").status, GateStatus.BLOCK)
        self.assertEqual(self.check({"ltp": 90.0}, "80").status, GateStatus.BLOCK)
        self.assertEqual(self.check({"ltp": 30.0, "ask": 31.0}, "80").status, GateStatus.PASS)
        self.assertEqual(self.check({}, "80").status, GateStatus.PASS)               # no price known: this check does not block (other checks handle that)


if __name__ == "__main__":
    unittest.main()
