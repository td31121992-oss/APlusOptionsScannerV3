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

    def test_daily_weak_tag(self):
        t = gsh.tags("BULLISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", 0.8)
        self.assertEqual((t["gs_daily_signed"], t["gs_daily_weak"]), (0.8, False))
        self.assertTrue(gsh.tags("BEARISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", 0.8)["gs_daily_weak"])        # daily up is against a put
        self.assertFalse(gsh.tags("BEARISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK", -0.7)["gs_daily_weak"])
        self.assertNotIn("gs_daily_weak", gsh.tags("BULLISH", 40, 11 * 60, 0.0, "HEALTHY_PULLBACK"))             # no daily score recorded

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
