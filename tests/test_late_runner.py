import csv
import gzip
import tempfile
import unittest
from pathlib import Path

import late_runner as lr


def snap(sym="AAA", direction="BULLISH", status="A_PLUS_WAIT_PIVOT_TO_R1", t="2026-10-26T10:00:00+05:30", **kw):
    row = {"time": t, "symbol": sym, "direction": direction, "status": status, "vwap_dist_pct": 1.0, "recent_15m_pct": 0.6, "rel_volume": 1.8, "tape_acc_15m": 0.9,
           "trend_retention_pct": 90, "range_position_pct": 92}
    row.update(kw)
    return row


class QualifyTests(unittest.TestCase):
    def test_bullish_and_bearish(self):
        self.assertTrue(lr.qualifies(snap()))
        self.assertFalse(lr.qualifies(snap(rel_volume=1.0)))
        self.assertFalse(lr.qualifies(snap(vwap_dist_pct=-0.2)))
        self.assertTrue(lr.qualifies(snap(direction="BEARISH", vwap_dist_pct=-1.0, recent_15m_pct=-0.6, range_position_pct=6)))   # raw snapshot values are negative for a put
        self.assertFalse(lr.qualifies(snap(direction="BEARISH", vwap_dist_pct=-1.0, recent_15m_pct=-0.6, range_position_pct=60)))  # not near the low

    def test_first_waits_prefers_the_first_qualifying_row(self):
        rows = [snap(t="a", rel_volume=0.8), snap(t="b"), snap(t="c", status="PASSED_ALL_GATES"), snap(sym="BBB", t="d", rel_volume=0.5)]
        out = {r["symbol"]: r for r in lr.first_waits(rows)}
        self.assertEqual((out["AAA"]["group"], out["AAA"]["time"]), ("QUALIFIED", "b"))
        self.assertEqual(out["BBB"]["group"], "CONTROL")


class OutcomeTests(unittest.TestCase):
    def test_which_came_first(self):
        self.assertEqual(lr.outcome([("10:05", 11), ("10:10", 14.5), ("10:15", 6)], 10)["first"], "T1")
        self.assertEqual(lr.outcome([("10:05", 6.5), ("10:10", 15)], 10)["first"], "SL")
        r = lr.outcome([("10:05", 11), ("10:10", 12)], 10)
        self.assertEqual((r["first"], r["peak_pct"], r["last_pct"]), ("OPEN", 20.0, 20.0))
        self.assertEqual(lr.outcome([], 10), {})


class DayTests(unittest.TestCase):
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "data" / "signal_snapshots").mkdir(parents=True)
            keys = list(snap().keys())
            with (root / "data" / "signal_snapshots" / "2026-10-26.csv").open("w", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=keys)
                w.writeheader()
                w.writerow(snap())
            cdir = root / "data" / "options_intelligence_upstox" / "2026-10-26"
            cdir.mkdir(parents=True)
            cols = ["captured_at", "symbol", "expiry", "spot", "strike", "side", "ltp", "bid", "ask"]
            with gzip.open(cdir / "option_chain_rows.csv.gz", "wt", encoding="utf-8", newline="") as h:
                w = csv.writer(h)
                w.writerow(cols)
                for t, p in (("10:01", 10), ("10:10", 12), ("10:20", 15)):
                    w.writerow([f"2026-10-26T{t}:00+05:30", "AAA", "2026-10-27", 100, 100, "CE", p, p - 0.1, p + 0.1])
                    w.writerow([f"2026-10-26T{t}:00+05:30", "AAA", "2026-10-27", 100, 140, "CE", 1, 0.9, 1.1])   # a far strike must not be picked
            rows = lr.day_rows("2026-10-26", root)
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["group"], rows[0]["strike"], rows[0]["first"]), ("QUALIFIED", 100.0, "T1"))
            self.assertEqual(rows[0]["entry"], 10.1)
            review = lr.run("2026-10-26", root)
            self.assertIn("QUALIFIED", review.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
