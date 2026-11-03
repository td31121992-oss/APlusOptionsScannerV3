import os
import unittest
from unittest import mock

for k in list(os.environ):
    if k.startswith("APLUS_WEAKMKT"):
        os.environ.pop(k)

import weak_market_gate as wk


class WeakMarketGateTests(unittest.TestCase):
    def test_mode(self):
        self.assertEqual(wk.mode(), "SHADOW")
        with mock.patch.dict(os.environ, {"APLUS_WEAKMKT_CE_MODE": "enforce"}):
            self.assertEqual(wk.mode(), "ENFORCE")
        with mock.patch.dict(os.environ, {"APLUS_WEAKMKT_CE_MODE": "x"}):
            self.assertEqual(wk.mode(), "SHADOW")

    def test_puts_and_missing_data_are_never_weak(self):
        self.assertEqual(wk.evaluate({"bs_breadth_pct": 10}, "BEARISH"), {})
        out = wk.evaluate({}, "BULLISH")
        self.assertEqual((out["wk_weak"], out["wk_ok"]), (0, 1))
        self.assertEqual(wk.evaluate({"bs_breadth_pct": "", "rule_nifty_pct_open": ""}, "BULLISH")["wk_weak"], 0)

    def test_weak_market_signals(self):
        a = wk.evaluate({"bs_breadth_pct": 38.0}, "BULLISH")
        self.assertEqual((a["wk_weak"], a["wk_ok"], a["wk_why"]), (1, 0, "breadth 38%"))
        b = wk.evaluate({"bs_breadth_pct": 60, "rule_nifty_pct_open": -0.31}, "BULLISH")
        self.assertEqual((b["wk_weak"], b["wk_ok"], b["wk_why"]), (1, 0, "nifty -0.31%"))
        c = wk.evaluate({"mb_would_block": 1.0}, "BULLISH")
        self.assertEqual((c["wk_why"], c["wk_ok"]), ("brake", 0))
        d = wk.evaluate({"bs_breadth_pct": 30, "rule_nifty_pct_open": -0.5, "mb_would_block": 1}, "BULLISH")
        self.assertEqual(d["wk_why"], "breadth 30%|nifty -0.50%|brake")
        fine = wk.evaluate({"bs_breadth_pct": 55, "rule_nifty_pct_open": 0.1, "mb_would_block": 0.0}, "BULLISH")
        self.assertEqual((fine["wk_weak"], fine["wk_ok"]), (0, 1))

    def test_overrides(self):
        weak = {"bs_breadth_pct": 30}
        news = wk.evaluate({**weak, "cat_dir": "BULLISH", "cat_conf": "HIGH", "cat_age_h": 6}, "BULLISH")
        self.assertEqual((news["wk_override"], news["wk_ok"]), ("NEWS", 1))
        self.assertEqual(wk.evaluate({**weak, "cat_dir": "BULLISH", "cat_conf": "LOW", "cat_age_h": 6}, "BULLISH")["wk_ok"], 0)       # weak wording is not news
        self.assertEqual(wk.evaluate({**weak, "cat_dir": "BULLISH", "cat_conf": "HIGH", "cat_age_h": 40}, "BULLISH")["wk_ok"], 0)     # stale
        self.assertEqual(wk.evaluate({**weak, "cat_dir": "BEARISH", "cat_conf": "HIGH", "cat_age_h": 1}, "BULLISH")["wk_ok"], 0)
        big = wk.evaluate({**weak, "bp_align": "WITH", "bp_net15_dir_cr": 2.4, "bp_conf": 3}, "BULLISH")
        self.assertEqual((big["wk_override"], big["wk_ok"]), ("BIG_BUYING", 1))
        self.assertEqual(wk.evaluate({**weak, "bp_align": "WITH", "bp_net15_dir_cr": 0.4, "bp_conf": 4}, "BULLISH")["wk_ok"], 0)     # not enough size
        self.assertEqual(wk.evaluate({**weak, "bp_align": "WITH", "bp_net15_dir_cr": 3.0, "bp_conf": 2}, "BULLISH")["wk_ok"], 0)     # not enough agreement
        self.assertEqual(wk.evaluate({**weak, "bp_align": "AGAINST", "bp_net15_dir_cr": -3.0, "bp_conf": 4}, "BULLISH")["wk_ok"], 0)

    def test_thresholds_are_settings(self):
        with mock.patch.dict(os.environ, {"APLUS_WEAKMKT_BREADTH_PCT": "30"}):
            self.assertEqual(wk.evaluate({"bs_breadth_pct": 38}, "BULLISH")["wk_weak"], 0)


if __name__ == "__main__":
    unittest.main()
