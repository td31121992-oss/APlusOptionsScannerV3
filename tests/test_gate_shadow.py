import json
import tempfile
import unittest
from pathlib import Path

import gate_review as gr
import gate_shadow as gsh


class GateTests(unittest.TestCase):
    def test_flags(self):
        f = gsh.flags("BULLISH", 85.0, 9 * 60 + 40, 0.5, "ESTABLISHED_TREND")
        self.assertEqual(f, {"premium80": True, "ce_early": True, "chasing": True, "est_trend": True})
        g = gsh.flags("BEARISH", 20.0, 9 * 60 + 40, 0.5, "HEALTHY_PULLBACK")        # stock UP 0.5% is against a put: not chasing
        self.assertEqual(g, {"premium80": False, "ce_early": False, "chasing": False, "est_trend": False})
        h = gsh.flags("BEARISH", 20.0, 11 * 60, -0.5, None)
        self.assertTrue(h["chasing"])
        self.assertIsNone(h["est_trend"])
        self.assertIsNone(gsh.flags("BULLISH", None, None, None)["premium80"])

    def test_tags(self):
        t = gsh.tags("BULLISH", 90, 9 * 60 + 30, 0.1, "ESTABLISHED_TREND")
        self.assertEqual((t["gs_premium80"], t["gs_ce_early"], t["gs_chasing"], t["gs_est_trend"], t["gs_count"]), (True, True, False, True, 3))
        self.assertEqual(gsh.tags("BULLISH", "bad", None, None, None).get("gs_count"), 0)

    def test_early945_tag(self):
        self.assertTrue(gsh.tags("BEARISH", 40, 9 * 60 + 44, 0.0, "HEALTHY_PULLBACK")["gs_early945"])
        self.assertFalse(gsh.tags("BEARISH", 40, 9 * 60 + 45, 0.0, "HEALTHY_PULLBACK")["gs_early945"])          # 09:45 itself is allowed
        self.assertNotIn("gs_early945", gsh.tags("BEARISH", 40, None, 0.0, "HEALTHY_PULLBACK"))
        self.assertEqual(gsh.tags("BEARISH", 40, 9 * 60 + 30, 0.0, "HEALTHY_PULLBACK")["gs_count"], 0)         # not part of the four-gate count

    def test_daily_weak_tag(self):
        t = gsh.tags("BULLISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", 0.8)
        self.assertEqual((t["gs_daily_signed"], t["gs_daily_weak"]), (0.8, False))
        self.assertTrue(gsh.tags("BEARISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", 0.8)["gs_daily_weak"])        # daily up is against a put
        self.assertFalse(gsh.tags("BEARISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", -0.7)["gs_daily_weak"])
        self.assertNotIn("gs_daily_weak", gsh.tags("BULLISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK"))             # no daily score recorded

    def test_quality_gates_spread_clean_score_and_pass(self):
        ok = gsh.tags("BULLISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", None, bid=9.95, ask=10.0, clean_score=97.0)
        self.assertEqual((ok["gs_spread_pct"], ok["gs_spread_wide"], ok["gs_clean_low"], ok["gs_q_block"], ok["gs_q_pass"]), (0.5, False, False, 0, True))
        wide = gsh.tags("BULLISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", None, bid=9.8, ask=10.0, clean_score=97.0)      # 2.0% spread
        self.assertEqual((wide["gs_spread_wide"], wide["gs_q_block"], wide["gs_q_pass"]), (True, 1, False))
        both = gsh.tags("BEARISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", None, bid=9.8, ask=10.0, clean_score=90.0)
        self.assertEqual((both["gs_clean_low"], both["gs_q_block"]), (True, 2))
        edge = gsh.tags("BULLISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", None, bid=9.9, ask=10.0, clean_score=96.0)      # exactly 1.0% and exactly 96: not blocked
        self.assertEqual((edge["gs_spread_wide"], edge["gs_clean_low"]), (False, False))
        self.assertNotIn("gs_q_pass", gsh.tags("BULLISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK"))                         # nothing known: no verdict
        self.assertNotIn("gs_spread_wide", gsh.tags("BULLISH", 40, 11 * 60, 0.0, "X", None, bid=0, ask=10.0))
        self.assertEqual(gsh.tags("BULLISH", 40, 11 * 60, 0.0, "X", None, bid="x", ask=None, clean_score="bad").get("gs_count"), 0)

    def test_lowprice_and_why(self):
        t = gsh.tags("BULLISH", 9.9, 9 * 60 + 30, 0.0, "ESTABLISHED_TREND")
        self.assertTrue(t["gs_lowprice"])
        self.assertEqual(t["gs_why"], "ce_early+est_trend+early945+lowprice")
        self.assertEqual(t["gs_why_n"], 4)
        self.assertFalse(gsh.tags("BULLISH", 10.0, 11 * 60, 0.0, "HEALTHY_PULLBACK")["gs_lowprice"])      # exactly 10 is allowed
        self.assertNotIn("gs_lowprice", gsh.tags("BULLISH", None, 11 * 60, 0.0, "X"))
        self.assertEqual(gsh.tags("BULLISH", 50, 11 * 60, 0.0, "HEALTHY_PULLBACK")["gs_why"], "")
        t.update({"gs_day_cap_over": True})
        self.assertTrue(gsh.why(t)["gs_why"].endswith("lowprice+day_cap_over"))

    def test_bear_weak_market_tag(self):
        t = gsh.tags("BEARISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", nifty_pct_open=0.1)
        self.assertEqual((t["gs_mkt_pct"], t["gs_bear_weakmkt"]), (0.1, True))
        self.assertIn("bear_weakmkt", t["gs_why"])
        self.assertFalse(gsh.tags("BEARISH", 40, 11 * 60, 0.0, "X", nifty_pct_open=0.2)["gs_bear_weakmkt"])        # exactly +0.2% is allowed
        self.assertFalse(gsh.tags("BULLISH", 40, 11 * 60, 0.0, "X", nifty_pct_open=-0.5)["gs_bear_weakmkt"])       # calls are not covered
        self.assertTrue(gsh.tags("BEARISH", 40, 11 * 60, 0.0, "X", nifty_pct_open=-0.6)["gs_bear_weakmkt"])
        self.assertNotIn("gs_bear_weakmkt", gsh.tags("BEARISH", 40, 11 * 60, 0.0, "X"))                          # no Nifty reading: no tag
        self.assertNotIn("gs_bear_weakmkt", gsh.tags("BEARISH", 40, 11 * 60, 0.0, "X", nifty_pct_open="bad"))

    def test_day_cap(self):
        self.assertFalse(gsh.over_cap(5))
        self.assertTrue(gsh.over_cap("6"))
        self.assertIsNone(gsh.over_cap(None))

    def test_evaluate_and_run(self):
        rows = []
        for i in range(40):
            rows.append({"day": f"2026-10-0{1 + i % 6}", "premium80": "1", "close": "-10", "fate": "A_PLUS", "best": "0"})
            rows.append({"day": f"2026-10-0{1 + i % 6}", "premium80": "0", "close": "5", "fate": "A_PLUS", "best": "0"})
        e = gr.evaluate(rows, "premium80")
        self.assertTrue(e["holds"])
        self.assertAlmostEqual(e["mean_blocked"], -10.0)
        self.assertFalse(gr.evaluate(rows[:4], "premium80")["holds"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mo = root / "data" / "missed_opportunities" / "2026-10-15"
            mo.mkdir(parents=True)
            (mo / "option_returns.json").write_text(json.dumps([
                {"symbol": "AAA", "dir": "BULLISH", "kind": "ATM", "fate": "TRADED", "ready": "09:40", "entry": 90.0, "close": -12, "best": 3, "stop_first": True}]), encoding="utf-8")
            syms = {"AAA": {"minute": [555 + 5 * i for i in range(10)], "close": [100, 100.2, 100.4, 100.8, 101.0, 101.2, 101.5, 101.8, 102, 102.2]}}
            path = gr.run("2026-10-15", root, syms)
            self.assertTrue(path.exists())
            row = path.read_text(encoding="utf-8").splitlines()[1]
            self.assertIn("AAA,BULLISH,09:40,TRADED,90.0,-12,3,1,1,1,1", row)          # premium80, ce_early and chasing all flagged
            self.assertIn("Entry-gate shadow review", (root / "data" / "shadow_rules" / "gate_review.md").read_text(encoding="utf-8"))
            self.assertIsNone(gr.run("2026-10-01", root))


if __name__ == "__main__":
    unittest.main()
