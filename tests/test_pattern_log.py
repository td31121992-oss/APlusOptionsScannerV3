import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pattern_log as pl

IST = timezone(timedelta(hours=5, minutes=30))


def day_candles(rows):
    """rows: list of (open, high, low, close, volume) from 09:15, 5 minutes apart."""
    t0 = datetime(2026, 10, 14, 9, 15, tzinfo=IST)
    return {"timestamp": [int((t0 + timedelta(minutes=5 * i)).timestamp()) for i in range(len(rows))],
            "open": [r[0] for r in rows], "high": [r[1] for r in rows], "low": [r[2] for r in rows],
            "close": [r[3] for r in rows], "volume": [r[4] for r in rows]}


class DetectTests(unittest.TestCase):
    def test_bullish_engulfing_records_forward_moves(self):
        rows = [(100, 100.5, 99.5, 100.2, 1000)] * 5
        rows += [(100.4, 100.5, 99.6, 99.8, 1000)]                      # small red bar
        rows += [(99.7, 101.2, 99.6, 101.0, 3000)]                       # engulfs it
        rows += [(101.0, 101.6, 100.9, 101.5, 1500)] * 12                # then drifts up
        events = pl.detect_events(day_candles(rows))
        eng = [e for e in events if e["pattern"] == "bullish_engulfing"]
        self.assertEqual(len(eng), 1)
        e = eng[0]
        self.assertEqual(e["time"], "09:45")
        self.assertEqual(e["price"], 101.0)
        self.assertAlmostEqual(e["f30"], (101.5 / 101.0 - 1) * 100, places=2)
        self.assertGreater(e["mfe60"], 0.4)

    def test_prev_day_high_break_and_sign_for_bearish(self):
        up = [(100, 100.3, 99.9, 100.1, 1000)] * 6 + [(100.1, 102, 100, 101.8, 2000)] + [(101.8, 102.2, 101.7, 102.0, 1000)] * 8
        ev = pl.detect_events(day_candles(up), prev_high=101.0)
        self.assertTrue(any(e["pattern"] == "prev_day_high_break" and e["time"] == "09:45" for e in ev))
        down = [(100, 100.3, 99.9, 100.1, 1000)] * 6 + [(100.1, 100.2, 98.0, 98.2, 2000)] + [(98.2, 98.3, 97.7, 97.8, 1000)] * 8
        ev = pl.detect_events(day_candles(down), prev_low=99.0)
        brk = [e for e in ev if e["pattern"] == "prev_day_low_break"]
        self.assertTrue(brk and brk[0]["f30"] > 0)                       # a fall after a bearish break counts as "worked"

    def test_too_short_day_gives_nothing(self):
        self.assertEqual(pl.detect_events(day_candles([(1, 1, 1, 1, 1)] * 4)), [])


class SummaryTests(unittest.TestCase):
    def test_summary_and_files(self):
        rows = [{"day": "2026-10-14", "pattern": "hammer", "minute": 600, "f30": "0.5", "f60": "0.8", "f_close": "1.0",
                 "mfe60": "1.2", "mae60": "-0.3"} for _ in range(3)]
        rows.append({"day": "2026-10-14", "pattern": "hammer", "minute": 700, "f30": "-0.4", "f60": "-0.2", "f_close": "-0.5",
                     "mfe60": "0.2", "mae60": "-0.9"})
        s = pl.summarize(rows)
        self.assertEqual(s["hammer"]["all"]["n"], 4)
        self.assertEqual(s["hammer"]["all"]["up30"], 75)
        self.assertEqual(s["hammer"]["buckets"]["09:15-10:30"]["n"], 3)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "data" / "pattern_log"
            folder.mkdir(parents=True)
            with (folder / "2026-10-14.csv").open("w", newline="", encoding="utf-8") as h:
                w = csv.DictWriter(h, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            path = pl.write_summary(Path(tmp), 10)
            self.assertTrue(path.exists())
            self.assertIn("hammer", path.read_text(encoding="utf-8"))
            self.assertEqual(json.loads((folder / "summary.json").read_text())["days"], ["2026-10-14"])


if __name__ == "__main__":
    unittest.main()


class ExtraPatternTests(unittest.TestCase):
    def names(self, rows):
        return {(e["pattern"], e["time"]) for e in pl.detect_events(day_candles(rows))}

    def test_morning_star_and_three_white_soldiers(self):
        base = [(100, 100.4, 99.6, 100.0, 1000)] * 4
        star = base + [(100.0, 100.1, 98.0, 98.2, 2000), (98.1, 98.4, 97.9, 98.0, 800), (98.2, 100.2, 98.1, 100.0, 2500)] + [(100, 100.3, 99.9, 100.1, 1000)] * 10
        self.assertIn(("morning_star", "09:45"), self.names(star))
        soldiers = base + [(100, 101, 99.9, 100.9, 1500), (100.9, 101.9, 100.8, 101.8, 1600), (101.8, 102.8, 101.7, 102.7, 1700)] + [(102.7, 102.9, 102.6, 102.8, 900)] * 10
        self.assertIn(("three_white_soldiers", "09:45"), self.names(soldiers))

    def test_bull_flag(self):
        rows = [(100, 100.3, 99.8, 100.0, 1000)] * 4
        rows += [(100.0, 100.4, 99.9, 100.35, 1500), (100.35, 100.8, 100.3, 100.75, 1600), (100.75, 101.2, 100.7, 101.15, 1800)]   # pole
        rows += [(101.1, 101.2, 100.9, 101.0, 600), (101.0, 101.15, 100.9, 101.05, 600), (101.05, 101.2, 100.95, 101.0, 600)]       # pause
        rows += [(101.0, 101.8, 100.95, 101.7, 2200)] + [(101.7, 101.9, 101.6, 101.8, 900)] * 8
        got = {e["pattern"] for e in pl.detect_events(day_candles(rows))}
        self.assertIn("bull_flag", got)

    def test_every_extra_pattern_has_a_side(self):
        import pattern_defs
        for name in pattern_defs.EXTRA_SIDES:
            self.assertIn(name, pl.PATTERNS)
