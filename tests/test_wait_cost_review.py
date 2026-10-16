import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import wait_cost_review as wc


def snap_rows():
    return [{"time": "2026-10-19T09:30:00", "symbol": "AAA", "direction": "BULLISH", "status": "A_PLUS_WAIT_LATE_VWAP_EXTENSION", "reasons": ""},
            {"time": "2026-10-19T09:38:00", "symbol": "AAA", "direction": "BULLISH", "status": "V2_STOCK_SELECTION_BLOCKED", "reasons": "Stock Selection V2 blocked: NOT_IN_DYNAMIC_TOP5_DIRECTION"},
            {"time": "2026-10-19T09:44:00", "symbol": "AAA", "direction": "BULLISH", "status": "PASSED_ALL_GATES", "reasons": ""},
            {"time": "2026-10-19T09:50:00", "symbol": "ZZZ", "direction": "BULLISH", "status": "A_PLUS_WAIT_PIVOT_TO_R1", "reasons": ""}]


class WaitCostTests(unittest.TestCase):
    def test_category(self):
        self.assertEqual(wc.category("A_PLUS_WAIT_LATE_10M_OVERHEAT"), "a_plus")
        self.assertEqual(wc.category("V2_STOCK_SELECTION_BLOCKED"), "v2")
        self.assertEqual(wc.category("PASSED_ALL_GATES"), "passed")
        self.assertEqual(wc.category("HELD_BACK"), "other")

    def test_timeline_splits_the_delay(self):
        rows = [r for r in snap_rows() if r["symbol"] == "AAA"]
        tl = wc.timeline(rows, datetime(2026, 10, 19, 9, 47))
        self.assertEqual(tl["mins"], {"a_plus": 8.0, "v2": 6.0, "passed": 3.0, "other": 0.0})
        self.assertEqual(tl["delay_min"], 17.0)
        self.assertIn("late_vwap_extension", tl["rules"])
        self.assertIn("not_in_dynamic_top5_direction", tl["v2"])
        self.assertIsNone(wc.timeline(rows, datetime(2026, 10, 19, 9, 0)))                   # entry before the first sighting

    def test_run_allocates_the_gap_and_summarises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sd = root / "data" / "signal_snapshots"
            sd.mkdir(parents=True)
            with (sd / "2026-10-19.csv").open("w", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=["time", "symbol", "direction", "status", "reasons"])
                w.writeheader()
                w.writerows(snap_rows())
            rep = root / "data" / "reports"
            rep.mkdir(parents=True)
            (rep / "paper_trade_history.json").write_text(json.dumps({"paper_trades": [
                {"paper_trade_id": "T1", "symbol": "AAA", "option_type": "CE", "entry_time": "2026-10-19T09:47:00", "option_security_id": "1"}]}), encoding="utf-8")
            ee = root / "data" / "shadow_rules" / "early_entry"
            ee.mkdir(parents=True)
            with (ee / "2026-10-19.csv").open("w", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=["day", "symbol", "dir", "flag_close", "act_close"])
                w.writeheader()
                w.writerow({"day": "2026-10-19", "symbol": "AAA", "dir": "BULLISH", "flag_close": 20, "act_close": 3})
            path = wc.run("2026-10-19", root)
            rows = list(csv.DictReader(path.open(encoding="utf-8")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(float(rows[0]["gap_points"]), 17.0)
            self.assertAlmostEqual(float(rows[0]["cost_a_plus"]), 8.0, places=1)              # 8 of 17 minutes
            self.assertAlmostEqual(float(rows[0]["cost_v2"]), 6.0, places=1)
            md = (root / "data" / "shadow_rules" / "wait_cost.md").read_text(encoding="utf-8")
            self.assertIn("What the waits cost", md)
            self.assertIn("A+ rules", md)
            self.assertIsNone(wc.run("2026-10-20", root))                                      # no snapshots that day


if __name__ == "__main__":
    unittest.main()
