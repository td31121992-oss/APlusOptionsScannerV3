import json
import tempfile
import unittest
from pathlib import Path

import pivot_review as pr


class PivotTests(unittest.TestCase):
    def test_pivots_and_state(self):
        v = pr.pivots(110.0, 90.0, 100.0)            # P=100, R1=110, S1=90
        self.assertAlmostEqual(v["P"], 100.0)
        self.assertAlmostEqual(v["R1"], 110.0)
        self.assertAlmostEqual(v["S1"], 90.0)
        self.assertEqual(pr.state(105.0, v), "PIVOT_TO_R1")
        self.assertEqual(pr.state(111.0, v), "R1_TO_R2")
        self.assertEqual(pr.state(95.0, v), "S1_TO_PIVOT")
        self.assertEqual(pr.state(85.0, v), "S2_TO_S1")
        self.assertEqual(pr.state(60.0, v), "BELOW_S3")

    def test_since_break_uses_first_close_beyond_level(self):
        v = pr.pivots(110.0, 90.0, 100.0)
        minutes = [555, 560, 565, 570, 575, 580]
        closes = [100.0, 111.0, 109.0, 112.0, 113.0, 114.0]
        sig = {"day": "d", "symbol": "X", "dir": "BULLISH", "ready": "09:40", "fate": "A_PLUS:late_vwap_extension", "close": 5, "best": 20, "stop_first": False}
        r = pr.tag_signal(sig, minutes, closes, v)
        self.assertEqual((r["state"], r["since_break"], r["rule"]), ("R1_TO_R2", 580 - 560, "late_vwap_extension"))
        sig["dir"] = "BEARISH"
        self.assertEqual(pr.tag_signal(sig, minutes, closes, v)["since_break"], "")        # never closed below S1
        sig["ready"] = "09:00"
        self.assertIsNone(pr.tag_signal(sig, minutes, closes, v))

    def test_verdict_bar(self):
        self.assertTrue(pr.verdict([]).startswith("not yet"))
        g = [{"day": f"2026-10-0{1 + i % 6}", "close": 8.0, "best": 20, "stop_first": 0} for i in range(40)]
        self.assertEqual(pr.verdict(g), "bar met")
        g1 = [{"day": "2026-10-01", "close": 8.0, "best": 20, "stop_first": 0} for _ in range(40)]
        self.assertIn("days", pr.verdict(g1))

    def test_run_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cd = root / "data" / "pattern_log" / "candles"
            cd.mkdir(parents=True)
            prev = {"symbols": {"AAA": {"minute": [555, 560], "high": [110.0, 110.0], "low": [90.0, 91.0], "close": [100.0, 100.0]}}}
            today = {"symbols": {"AAA": {"minute": [555, 560, 565], "high": [1, 1, 1], "low": [1, 1, 1], "close": [100.0, 112.0, 113.0]}}}
            (cd / "2026-10-14.json").write_text(json.dumps(prev), encoding="utf-8")
            (cd / "2026-10-15.json").write_text(json.dumps(today), encoding="utf-8")
            mo = root / "data" / "missed_opportunities" / "2026-10-15"
            mo.mkdir(parents=True)
            (mo / "option_returns.json").write_text(json.dumps([
                {"symbol": "AAA", "dir": "BULLISH", "fate": "TRADED", "ready": "09:25", "kind": "ATM", "best": 30, "worst": -5, "close": 12, "stop_first": False},
                {"symbol": "ZZZ", "dir": "BULLISH", "fate": "TRADED", "ready": "09:25", "kind": "ATM", "best": 1, "worst": 1, "close": 1, "stop_first": False}]), encoding="utf-8")
            path = pr.run("2026-10-15", root)
            rows = pr.load(root)
            self.assertEqual(len(rows), 1)                                     # ZZZ has no candles
            self.assertEqual(rows[0]["state"], "R1_TO_R2")
            self.assertTrue((root / "data" / "shadow_rules" / "pivot_review.md").read_text(encoding="utf-8").startswith("# Pivot-state"))
            self.assertTrue(path.exists())
            self.assertIsNone(pr.run("2026-10-01", root))                      # no previous session on file


if __name__ == "__main__":
    unittest.main()
