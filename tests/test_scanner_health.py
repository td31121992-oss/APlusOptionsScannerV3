import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import scanner_health as sh
import trade_review as tr

DAY = "2026-10-13"


def make_day(root, day, minutes, per_minute=1, offset=0):
    folder = Path(root, "data", "reports")
    folder.mkdir(parents=True, exist_ok=True)
    compact = day.replace("-", "")
    for m in minutes:
        for k in range(per_minute):
            sec = (offset + k * 30) % 60
            Path(folder, f"intraday_movement_{compact}_{m // 60:02d}{m % 60:02d}{sec:02d}.json").write_text("{}")


def mins(a, b):
    return range(a[0] * 60 + a[1], b[0] * 60 + b[1] + 1)


class HealthTests(unittest.TestCase):
    def test_full_day_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_day(tmp, DAY, mins((9, 15), (15, 30)))
            h = sh.day_health(DAY, tmp, now=datetime(2026, 10, 14, 8, 0))
            self.assertEqual((h["status"], h["reasons"]), ("CLEAN", []))
            self.assertIn("CLEAN", sh.line(h))

    def test_late_start_and_gap_are_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            ms = list(mins((11, 46), (13, 0))) + list(mins((13, 30), (15, 30)))
            make_day(tmp, DAY, ms)
            h = sh.day_health(DAY, tmp, now=datetime(2026, 10, 14, 8, 0))
            self.assertEqual(h["status"], "PARTIAL")
            for r in ("LATE_START", "GAPS", "LOW_COVERAGE"):
                self.assertIn(r, h["reasons"])
            self.assertAlmostEqual(h["longest_gap_min"], 30, delta=1.1)
            self.assertIn("started 11:46 (late)", sh.line(h))

    def test_two_scanners_is_double_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_day(tmp, DAY, mins((9, 15), (15, 30)), per_minute=2)
            h = sh.day_health(DAY, tmp, now=datetime(2026, 10, 14, 8, 0))
            self.assertIn("DOUBLE_RUN", h["reasons"])
            self.assertEqual(h["status"], "PARTIAL")

    def test_today_is_in_progress_and_not_penalised_for_unfinished_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_day(tmp, "2026-10-14", mins((9, 15), (11, 0)))
            h = sh.day_health("2026-10-14", tmp, now=datetime(2026, 10, 14, 11, 1))
            self.assertEqual((h["status"], h["reasons"]), ("IN_PROGRESS", []))

    def test_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sh.day_health(DAY, tmp)["status"], "NO_DATA")
            self.assertIn("NO DATA", sh.line(sh.day_health(DAY, tmp)))

    def test_review_shows_the_line(self):
        rows = [{"net": 100, "gross": 120, "costs": 20, "status": "CLOSED"}]
        self.assertIn("Scanner health: PARTIAL", tr.render(DAY, [], health="**Scanner health: PARTIAL** - x"))
        self.assertTrue(callable(tr.render))


if __name__ == "__main__":
    unittest.main()
