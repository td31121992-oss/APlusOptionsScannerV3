import json
import tempfile
import unittest
from pathlib import Path

import rule_scorecard as rs


def rows(day, spec):
    out = []
    for fate, ready, best, worst, close, n in spec:
        for _ in range(n):
            out.append({"symbol": "X", "dir": "BULLISH", "fate": fate, "ready": ready, "strike": 100, "kind": "ATM", "entry": 10,
                        "best": best, "worst": worst, "close": close})
    return out


class ScorecardTests(unittest.TestCase):
    def make(self, tmp):
        root = Path(tmp)
        for day, spec in (("2026-10-13", [("TRADED", "10:00", 30, -10, 10, 8), ("A_PLUS:late_vwap_extension", "10:05", 45, -8, 25, 9),
                                         ("A_PLUS:late_10m_overheat", "09:30", 5, -30, -25, 9), ("V2_BLOCKED", "10:10", 20, -12, 2, 8)]),
                          ("2026-10-14", [("TRADED", "10:20", 28, -9, 8, 3), ("A_PLUS:late_vwap_extension", "10:25", 40, -9, 20, 2)])):
            f = root / "data" / "missed_opportunities" / day
            f.mkdir(parents=True)
            (f / "option_returns.json").write_text(json.dumps(rows(day, spec)))
        # a pre-baseline day and a non-ATM row must be ignored
        old = root / "data" / "missed_opportunities" / "2026-09-23"
        old.mkdir(parents=True)
        (old / "option_returns.json").write_text(json.dumps(rows("2026-09-23", [("TRADED", "10:00", 99, 0, 99, 5)])))
        return root

    def test_groups_buckets_and_traded_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make(tmp)
            card = rs.build(rs.load_rows(root))
            self.assertEqual(card["days"], ["2026-10-13", "2026-10-14"])
            late = card["groups"]["late_vwap_extension"]["buckets"]["09:45-10:30"]
            self.assertEqual((late["n"], late["reach15"], late["reach30"], late["median_close"]), (11, 100, 100, 25))
            self.assertEqual(card["groups"]["late_10m_overheat"]["buckets"]["before 09:45"]["mean_close"], -25.0)
            self.assertEqual(card["groups"]["TRADED"]["all"]["n"], 11)             # the pre-baseline 99% rows are excluded
            md = rs.render(card)
            self.assertIn("late_vwap_extension", md)
            self.assertIn("at least as good as the traded ones", md)
            self.assertIn("**late_vwap_extension**", md)
            self.assertNotIn("**late_10m_overheat**", md.split("## 09:45-10:30")[1].split("## 10:30-12:00")[0])

    def test_write_creates_files_and_empty_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(rs.write(Path(tmp)))
            root = self.make(tmp)
            p = rs.write(root)
            self.assertTrue(p.exists())
            self.assertTrue((root / "data" / "shadow_rules" / "scorecard.json").exists())


if __name__ == "__main__":
    unittest.main()
