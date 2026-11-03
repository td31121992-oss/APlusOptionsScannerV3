from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from trading_calendar import is_trading_day


class TradingCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "nse_holidays.csv"
        self.file.write_text("date,description\n2026-10-20,Dussehra\n", encoding="utf-8")

    def test_normal_weekday_is_trading_day(self) -> None:
        self.assertEqual(is_trading_day(date(2026, 10, 7), self.file, {}), (True, "TRADING_DAY"))

    def test_listed_holiday_is_blocked_with_reason(self) -> None:
        ok, reason = is_trading_day(date(2026, 10, 20), self.file, {})
        self.assertFalse(ok)
        self.assertIn("Dussehra", reason)

    def test_weekend_is_blocked(self) -> None:
        self.assertEqual(is_trading_day(date(2026, 10, 3), self.file, {}), (False, "WEEKEND"))
        self.assertEqual(is_trading_day(date(2026, 10, 4), self.file, {}), (False, "WEEKEND"))

    def test_force_override_allows_special_saturday(self) -> None:
        ok, _ = is_trading_day(date(2026, 10, 3), self.file, {"APLUS_FORCE_TRADING_DAY": "1"})
        self.assertTrue(ok)

    def test_missing_holiday_file_fails_open_on_weekday(self) -> None:
        ok, reason = is_trading_day(date(2026, 10, 20), Path(self.tmp.name) / "nope.csv", {})
        self.assertTrue(ok)
        self.assertEqual(reason, "TRADING_DAY")

    def test_corrupt_holiday_file_fails_open(self) -> None:
        bad = Path(self.tmp.name) / "bad.csv"
        bad.write_bytes(b"\xff\xfe\x00garbage\x00\x01")
        self.assertTrue(is_trading_day(date(2026, 10, 20), bad, {})[0])

    def test_real_2026_holidays_file_if_present(self) -> None:
        real = Path(__file__).resolve().parents[1] / "data" / "safety" / "nse_holidays.csv"
        if real.exists() and real.stat().st_size > 100:
            self.assertFalse(is_trading_day(date(2026, 10, 2), real, {})[0])   # Gandhi Jayanti
            self.assertTrue(is_trading_day(date(2026, 10, 8), real, {})[0])


if __name__ == "__main__":
    unittest.main()
