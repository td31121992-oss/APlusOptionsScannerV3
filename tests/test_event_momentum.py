import csv
import json
import tempfile
import unittest
from pathlib import Path

import event_momentum as em

SNAP_FIELDS = ["time", "symbol", "direction", "status", "rel_volume", "day_change_pct", "gap_pct"]


def snap(root, day, rows):
    d = root / "data" / "signal_snapshots"
    d.mkdir(parents=True, exist_ok=True)
    with (d / f"{day}.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=SNAP_FIELDS)
        w.writeheader()
        w.writerows(rows)


def outcomes(root, day, items):
    d = root / "data" / "missed_opportunities" / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "option_returns.json").write_text(json.dumps([{"kind": "ATM", "ready": "09:30", **i} for i in items]), encoding="utf-8")


class EvaluateTests(unittest.TestCase):
    def test_core_loose_and_direction(self):
        e = em.evaluate(45.9, -9.32, -3.05, "BEARISH", "A_PLUS_WAIT_LATE_10M_OVERHEAT")
        self.assertEqual((e["em_core"], e["em_loose"], e["em_blocked"], e["em_move_dir"], e["em_gap_dir"]), (1, 1, 1, 9.32, 3.05))
        self.assertEqual(em.evaluate(45.9, -9.32, -3.05, "BULLISH")["em_core"], 0)                 # a call against the fall is not event momentum
        self.assertEqual(em.evaluate(6.0, 3.5, 0.5, "BULLISH")["em_core"], 0)                       # volume too low for core ...
        self.assertEqual(em.evaluate(6.0, 3.5, 0.5, "BULLISH")["em_loose"], 1)                      # ... but loose
        self.assertEqual(em.evaluate(9.0, 1.0, 0.0, "BULLISH")["em_core"], 0)                       # barely moved
        self.assertEqual(em.evaluate(9.0, 4.0, 0.0, "BULLISH", "PASSED_ALL_GATES")["em_blocked"], 0)
        self.assertEqual(em.evaluate(None, 4.0, 0.0, "BULLISH"), {})

    def test_tags_from_a_candidate_record(self):
        t = em.tags({"relative_volume": 12.0, "day_change_percent": -4.0, "gap_percent": -1.0}, "BEARISH")
        self.assertEqual((t["em_core"], t["em_rvol"]), (1, 12.0))
        self.assertEqual(em.tags({}, "BEARISH"), {})


class ReviewTests(unittest.TestCase):
    def test_review_groups_and_forward_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snap(root, "2026-10-21", [
                {"time": "09:30:00", "symbol": "AAA", "direction": "BEARISH", "status": "A_PLUS_WAIT_LATE_10M_OVERHEAT", "rel_volume": 10, "day_change_pct": -5, "gap_pct": -2},
                {"time": "09:31:00", "symbol": "BBB", "direction": "BULLISH", "status": "PASSED_ALL_GATES", "rel_volume": 1.2, "day_change_pct": 0.4, "gap_pct": 0.1},
                {"time": "09:32:00", "symbol": "CCC", "direction": "BULLISH", "status": "V2_STOCK_SELECTION_BLOCKED", "rel_volume": 6, "day_change_pct": 3.5, "gap_pct": 1}])
            outcomes(root, "2026-10-21", [{"symbol": "AAA", "dir": "BEARISH", "best": 150, "worst": -5, "close": 120, "stop_first": False},
                                           {"symbol": "BBB", "dir": "BULLISH", "best": 20, "worst": -30, "close": -25, "stop_first": True},
                                           {"symbol": "CCC", "dir": "BULLISH", "best": 40, "worst": -10, "close": 10, "stop_first": False}])
            out = em.review(root, "2026-10-21")
            text = out.read_text(encoding="utf-8")
            self.assertIn("| Event momentum, HELD BACK by a rule (the case this is about) | 1 | 0% | 100% ", text)
            self.assertIn("| Loose event momentum (5x volume, 3 % with us), not core | 1 |", text)
            self.assertIn("| Everything else | 1 | 100% | 0% ", text)
            self.assertIn("No forward days yet", text)                                              # registered on this first run
            self.assertEqual(json.loads((root / "data" / "event_momentum" / "registered.json").read_text(encoding="utf-8"))["day"], "2026-10-21")
            snap(root, "2026-10-22", [{"time": "09:30:00", "symbol": "DDD", "direction": "BEARISH", "status": "A_PLUS_WAIT_LATE_VWAP_EXTENSION", "rel_volume": 9, "day_change_pct": -3, "gap_pct": -1}])
            outcomes(root, "2026-10-22", [{"symbol": "DDD", "dir": "BEARISH", "best": 90, "worst": -3, "close": 60, "stop_first": False}])
            text2 = em.review(root, "2026-10-22").read_text(encoding="utf-8")
            self.assertIn("Forward only (days after 2026-10-21", text2)
            self.assertIn("so far 1", text2)                                                        # DDD is the one forward held-back signal
            self.assertEqual(em.wilson(0, 0), None)

    def test_nothing_to_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(em.review(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
