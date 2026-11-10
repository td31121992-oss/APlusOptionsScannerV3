import csv
import tempfile
import unittest
from pathlib import Path

import trade_archive as ta


def trade(i, sym="ABB", when="2026-11-09T10:00:00", **kw):
    base = {"paper_trade_id": i, "symbol": sym, "option_security_id": "1", "entry_time": when, "exit_time": "2026-11-09T11:00:00", "status": "CLOSED",
            "net_pnl": 100.0, "entry_price": 10.0, "quantity": 100, "sf_would_block": "False", "rgs_would_block": "False", "sf_focus_block": "False", "sf_stack_block": "False"}
    base.update(kw)
    return base


class ArchiveTests(unittest.TestCase):
    def test_written_once_then_unchanged_then_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            t = [trade("a")]
            p1, how1 = ta.archive_day("2026-11-09", t, folder)
            p2, how2 = ta.archive_day("2026-11-09", t, folder)
            p3, how3 = ta.archive_day("2026-11-09", t + [trade("b", "TCS")], folder)
            self.assertEqual((how1, how2, how3), ("written", "unchanged", "revision"))
            self.assertEqual(p1, p2)
            self.assertEqual(p3.name, "2026-11-09.r2.json")
            self.assertTrue(p1.exists())


class IntegrityTests(unittest.TestCase):
    def test_clean_day_has_no_issues(self):
        self.assertEqual(ta.integrity("2026-11-09", [trade("a"), trade("b", "TCS", option_security_id="2")], today="2026-11-10"), [])

    def test_duplicates_open_and_session_problems_are_flagged(self):
        rows = [trade("a"), trade("a", "TCS", option_security_id="2"), trade("c"), trade("d", "INFY", when="2026-11-09T15:50:00", option_security_id="3"),
                trade("e", "SBIN", status="OPEN", exit_time="", option_security_id="4"), trade("f", "HDFC", entry_price=0, option_security_id="5")]
        text = " | ".join(ta.integrity("2026-11-09", rows, today="2026-11-10"))
        for needle in ("duplicate paper_trade_id", "same contract entered twice", "still OPEN", "outside 09:15-15:30", "not positive"):
            self.assertIn(needle, text)

    def test_missing_shadow_tags_are_reported(self):
        rows = [trade("a", sf_would_block=""), trade("b", "TCS", option_security_id="2")]
        self.assertEqual(ta.integrity("2026-11-09", rows, today="2026-11-10"), [])
        self.assertIn("sf_would_block present on 1/2", " ".join(ta.tag_notes(rows)))
        self.assertEqual(ta.tag_notes([trade("a", sf_would_block="", rgs_would_block="", sf_focus_block="", sf_stack_block="")]), [])


class RuleHistoryTests(unittest.TestCase):
    def test_rerunning_a_day_replaces_only_that_day(self):
        gate = lambda net: [{"rule": "R", "trades_with_data": 5, "blocked": {"n": 2, "net": net}, "allowed": {"n": 3, "net": 1}, "change_if_enforced": -net, "days_helped": 1,
                             "days_blocked": 1, "enough": False}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rule_history.csv"
            ta.write_rule_history("2026-11-06", gate(5), path)
            ta.write_rule_history("2026-11-09", gate(7), path)
            ta.write_rule_history("2026-11-09", gate(9), path)
            rows = list(csv.DictReader(path.open(encoding="utf-8")))
            self.assertEqual([(r["day"], r["blocked_net"]) for r in rows], [("2026-11-06", "5"), ("2026-11-09", "9")])


if __name__ == "__main__":
    unittest.main()
