import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import event_tags as et
import trade_journal as tj


def at(h, m, s=0):
    return datetime(2026, 10, 13, h, m, s)


def row(sym, gap, move, ltp=100.0, sector="IT"):
    return {"symbol": sym, "gap_pct": gap, "from_open_pct": move, "ltp": ltp, "sector": sector}


class EventTagTests(unittest.TestCase):
    def test_expected_fraction_interpolates(self):
        self.assertAlmostEqual(et.expected_fraction(0), 0.0)
        self.assertAlmostEqual(et.expected_fraction(15), 0.079)
        self.assertAlmostEqual(et.expected_fraction(45), 0.171)
        self.assertGreater(et.expected_fraction(30), 0.079)
        self.assertLess(et.expected_fraction(30), 0.171 + 1e-9)
        self.assertEqual(et.expected_fraction(1000), 1.0)

    def test_event_like_needs_gap_and_volume(self):
        # at 10:00 (45 min) the market has normally done 17.1% of its day volume: 1,000,000 avg -> 171,000 expected
        e = et.evaluate(row("AAA", 3.0, 1.2), 600_000, 1_000_000, at(10, 0))
        self.assertTrue(e["event_like"])
        self.assertGreater(e["event_rvol"], 3)
        self.assertTrue(e["event_agrees"])
        self.assertFalse(et.evaluate(row("AAA", 1.0, 1.2), 600_000, 1_000_000, at(10, 0))["event_like"])        # small gap
        self.assertFalse(et.evaluate(row("AAA", 3.0, 1.2), 150_000, 1_000_000, at(10, 0))["event_like"])        # normal volume
        self.assertFalse(et.evaluate(row("AAA", 3.0, -0.8), 600_000, 1_000_000, at(10, 0))["event_agrees"])      # move reversed the gap
        self.assertTrue(et.evaluate(row("AAA", -3.0, -0.8), 600_000, 1_000_000, at(10, 0))["event_agrees"])      # gap down, still falling

    def test_missing_volume_or_average_is_not_an_event(self):
        self.assertFalse(et.evaluate(row("AAA", 4.0, 1.0), 0, 1_000_000, at(10, 0))["event_like"])
        self.assertFalse(et.evaluate(row("AAA", 4.0, 1.0), 900_000, 0, at(10, 0))["event_like"])

    def test_checkpoint_log_is_written_once_per_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, state = Path(tmp), {}
            rows = [row("AAA", 3.0, 1.0), row("BBB", 0.2, 0.1)]
            vols, ind = {"AAA": 600_000, "BBB": 600_000}, {"AAA": {"avg_vol20": 1_000_000}, "BBB": {"avg_vol20": 1_000_000}}
            self.assertEqual(et.observe(rows, vols, ind, at(9, 20, 5), state, root), 1)                     # AAA only
            self.assertEqual(et.observe(rows, vols, ind, at(9, 21, 5), state, root), 0)                     # same checkpoint: not repeated
            self.assertEqual(et.observe(rows, vols, ind, at(9, 31, 5), state, root), 1)                     # 09:30 checkpoint
            self.assertEqual(et.observe(rows, vols, ind, at(10, 3, 0), state, root), 1)                     # 09:45 and 10:00 both due: latest only
            self.assertEqual(et.observe(rows, vols, ind, at(10, 4, 0), state, root), 0)
            self.assertEqual(et.observe(rows, vols, ind, at(11, 0, 0), state, root), 0)                     # after the window
            data = list(csv.DictReader((root / "data" / "event_days" / "2026-10-13.csv").open(encoding="utf-8")))
            self.assertEqual([d["checkpoint"] for d in data], ["09:20", "09:30", "10:00"])
            self.assertEqual({d["symbol"] for d in data}, {"AAA"})
            self.assertEqual(data[0]["agrees"], "1")

    def test_trade_tags_and_journal_text(self):
        tags = et.trade_tags("AAA", [row("AAA", 3.0, 1.0)], {"AAA": 600_000}, {"AAA": {"avg_vol20": 1_000_000}}, at(10, 0))
        self.assertTrue(tags["event_like"])
        self.assertEqual(et.trade_tags("ZZZ", [row("AAA", 3.0, 1.0)], {}, {}, at(10, 0)), {})
        text = tj._event_text({**tags})
        self.assertIn("EVENT-LIKE", text)
        self.assertIn("agrees with the gap", text)
        self.assertEqual(tj._event_text({}), "")                                                         # an older trade without the tag
        self.assertEqual(tj._event_text({"event_like": False}), "not an event day")


if __name__ == "__main__":
    unittest.main()
