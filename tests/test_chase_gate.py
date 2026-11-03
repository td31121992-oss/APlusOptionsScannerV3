import os
import unittest
from unittest import mock

for k in list(os.environ):
    if k.startswith("APLUS_CHASE"):
        os.environ.pop(k)

import chase_gate as cg


class ChaseGateTests(unittest.TestCase):
    def test_mode(self):
        self.assertEqual(cg.mode(), "SHADOW")
        with mock.patch.dict(os.environ, {"APLUS_CHASE_GATE_MODE": "enforce"}):
            self.assertEqual(cg.mode(), "ENFORCE")
        with mock.patch.dict(os.environ, {"APLUS_CHASE_GATE_MODE": "zzz"}):
            self.assertEqual(cg.mode(), "SHADOW")

    def test_fast_run_is_a_chase_in_either_direction(self):
        for d in ("BULLISH", "BEARISH"):
            o = cg.evaluate({"ctx_last15_pct": 0.45}, d)
            self.assertEqual((o["cg_fast"], o["cg_ok"], o["cg_why"]), (1, 0, "stock +0.45% in 15m"))
            ok = cg.evaluate({"ctx_last15_pct": 0.10}, d)
            self.assertEqual((ok["cg_fast"], ok["cg_ok"], ok["cg_why"]), (0, 1, ""))
        self.assertEqual(cg.evaluate({"ctx_last15_pct": 0.30}, "BULLISH")["cg_fast"], 1)           # the threshold itself counts
        self.assertEqual(cg.evaluate({"ctx_last15_pct": -0.8}, "BULLISH")["cg_ok"], 1)             # moving against us is not chasing

    def test_extended_market_applies_to_calls_only(self):
        call = cg.evaluate({"bs_breadth_pct": 72}, "BULLISH")
        self.assertEqual((call["cg_extended"], call["cg_ok"], call["cg_why"]), (1, 0, "market extended 72%"))
        self.assertEqual(cg.evaluate({"bs_breadth_pct": 60}, "BULLISH")["cg_ok"], 1)               # needs to be more than 60
        put = cg.evaluate({"bs_breadth_pct": 90}, "BEARISH")
        self.assertNotIn("cg_extended", put)
        self.assertEqual(put["cg_ok"], 1)                                                           # puts with most of the market below VWAP did fine in the data

    def test_both_conditions_and_missing_data(self):
        both = cg.evaluate({"ctx_last15_pct": 0.5, "bs_breadth_pct": 80}, "BULLISH")
        self.assertEqual(both["cg_why"], "stock +0.50% in 15m|market extended 80%")
        self.assertEqual(cg.evaluate({}, "BULLISH"), {"cg_why": "", "cg_ok": 1})
        self.assertEqual(cg.evaluate({"ctx_last15_pct": "", "bs_breadth_pct": None}, "BULLISH")["cg_ok"], 1)
        extras = cg.evaluate({"ctx_done_move_pct": 2.4, "ctx_range_pos": 0.95}, "BEARISH")
        self.assertEqual((extras["cg_done_pct"], extras["cg_range_pos"], extras["cg_ok"]), (2.4, 0.95, 1))      # tag-only: even a stretched day does not block
        with mock.patch.dict(os.environ, {"APLUS_CHASE_LAST15_PCT": "0.6"}):
            self.assertEqual(cg.evaluate({"ctx_last15_pct": 0.45}, "BULLISH")["cg_ok"], 1)


if __name__ == "__main__":
    unittest.main()
