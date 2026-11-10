import os
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

import pipeline_watchdog as pw

WEEKDAYS = lambda d: d.weekday() < 5                          # calendar stand-in: weekends closed, no holidays
HOLIDAY_TUE = lambda d: d.weekday() < 5 and d != date(2026, 11, 10)


def touch(path: Path, when: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (when.timestamp(), when.timestamp()))


class DueDayTests(unittest.TestCase):
    def test_before_deadline_uses_previous_trading_day(self):
        self.assertEqual(pw.due_day(datetime(2026, 11, 11, 9, 0), time(16, 50), WEEKDAYS), date(2026, 11, 10))
        self.assertEqual(pw.due_day(datetime(2026, 11, 11, 17, 0), time(16, 50), WEEKDAYS), date(2026, 11, 11))

    def test_weekend_and_holiday_are_skipped(self):
        self.assertEqual(pw.due_day(datetime(2026, 11, 9, 9, 0), time(16, 50), WEEKDAYS), date(2026, 11, 6))      # Monday morning -> Friday
        self.assertEqual(pw.due_day(datetime(2026, 11, 10, 20, 0), time(16, 50), HOLIDAY_TUE), date(2026, 11, 9))  # holiday evening -> Monday

    def test_trading_days_behind(self):
        self.assertEqual(pw.trading_days_between(date(2026, 10, 30), date(2026, 11, 9), HOLIDAY_TUE), 6)


class EvaluateTests(unittest.TestCase):
    def test_ok_stale_and_missing(self):
        now = datetime(2026, 11, 11, 18, 0)                                       # Wednesday evening, Tuesday 10 Nov is a holiday
        c = pw.Check("Scoreboard", "data/shadow_scoreboard/{day}.md", time(16, 50), written_after=None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(pw.evaluate(c, now, root, WEEKDAYS)["status"], "MISSING")
            touch(root / "data/shadow_scoreboard/2026-11-11.md", datetime(2026, 11, 11, 16, 30))
            self.assertEqual(pw.evaluate(c, now, root, WEEKDAYS)["status"], "OK")
            d = pw.Check("Reviews", "data/shadow_rules/x", time(17, 30), "dir")
            touch(root / "data/shadow_rules/x/a.csv", datetime(2026, 10, 30, 16, 0))
            r = pw.evaluate(d, now, root, WEEKDAYS)
            self.assertEqual(r["status"], "STALE")
            self.assertIn("trading day(s) behind", r["detail"])
            touch(root / "data/shadow_rules/x/b.csv", datetime(2026, 11, 11, 15, 56))
            self.assertEqual(pw.evaluate(d, now, root, WEEKDAYS)["status"], "OK")

    def test_write_before_close_does_not_count(self):
        now = datetime(2026, 11, 11, 16, 0)
        c = pw.Check("Report", "data/r.json", time(15, 45))
        with tempfile.TemporaryDirectory() as tmp:
            touch(Path(tmp) / "data/r.json", datetime(2026, 11, 11, 11, 0))      # written mid-session: the close has not been captured
            self.assertEqual(pw.evaluate(c, now, Path(tmp), WEEKDAYS)["status"], "STALE")


class RunTests(unittest.TestCase):
    def test_no_telegram_run_writes_status_and_returns_failure_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = pw.run(datetime(2026, 11, 11, 18, 0), Path(tmp), telegram=False)
            self.assertEqual(code, 1)
            self.assertTrue((Path(tmp) / "data" / "pipeline_health.json").exists())
            self.assertIn("Not current", (Path(tmp) / "data" / "pipeline_health.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
