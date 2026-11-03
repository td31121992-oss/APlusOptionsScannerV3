from __future__ import annotations

import os
import types
import unittest
from datetime import datetime, time as clock_time
from unittest import mock
from zoneinfo import ZoneInfo

from config import OpeningMomentumConfig
from option_selector import OptionSelectionConfig
import opening_momentum_scanner as scanner

IST = ZoneInfo("Asia/Kolkata")


def _allowed(settings, hh: int, mm: int) -> bool:
    fake = types.SimpleNamespace(settings=settings)
    now = datetime(2026, 10, 7, hh, mm, tzinfo=IST)
    return scanner.OpeningMomentumScanner._new_entries_allowed(fake, now)


class EntryCutoffTests(unittest.TestCase):
    def test_default_cutoff_is_1300(self) -> None:
        self.assertEqual(OpeningMomentumConfig().last_new_entry_time, clock_time(13, 0))

    def test_entries_allowed_before_cutoff_and_blocked_after(self) -> None:
        s = OpeningMomentumConfig()
        self.assertTrue(_allowed(s, 9, 30))
        self.assertTrue(_allowed(s, 13, 0))
        self.assertFalse(_allowed(s, 13, 1))
        self.assertFalse(_allowed(s, 14, 30))

    def test_before_session_start_blocked(self) -> None:
        self.assertFalse(_allowed(OpeningMomentumConfig(), 9, 0))

    def test_cutoff_can_be_disabled_with_session_end_time(self) -> None:
        s = OpeningMomentumConfig(last_new_entry_time=clock_time(15, 30))
        self.assertTrue(_allowed(s, 14, 30))

    def test_env_override(self) -> None:
        from config import AppConfig
        with mock.patch.dict(os.environ, {"INTRADAY_LAST_NEW_ENTRY": "12:15"}):
            cfg = AppConfig.from_env()
        self.assertEqual(cfg.opening_momentum.last_new_entry_time, clock_time(12, 15))


class SpreadCapTests(unittest.TestCase):
    def test_default_spread_cap_is_2_percent(self) -> None:
        self.assertEqual(OptionSelectionConfig().maximum_spread_percent, 2.0)

    def test_env_can_override_spread_cap(self) -> None:
        with mock.patch.dict(os.environ, {"APLUS_OPTION_MAX_SPREAD_PERCENT": "3.5"}):
            self.assertEqual(OptionSelectionConfig.from_env().maximum_spread_percent, 3.5)


if __name__ == "__main__":
    unittest.main()
