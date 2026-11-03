from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "self_healing_watchdog" / "telegram_health_check.py"
spec = importlib.util.spec_from_file_location("telegram_health_check", SCRIPT)
thc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(thc)

NOW = datetime(2026, 10, 8, 9, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
GOOD_ITEMS = {
    "Dhan token": {"level": "ok", "value": "22.5 h left"},
    "Supervisor": {"level": "ok", "value": "alive (8s ago)"},
    "Market-data authorization": {"level": "ok", "value": "Healthy"},
    "MWPL / ban data": {"level": "ok", "value": "as of 2026-10-07", "detail": "3 stocks in F&O ban"},
    "Corporate events": {"level": "ok", "value": "188 events"},
}
TASKS_OK = {"APlusOptionsScannerV3_MorningStart": True, "APlus_Master_Self_Healing": True}


class BuildMessageTests(unittest.TestCase):
    def test_ready_when_all_good_and_scanner_not_yet_started_is_not_an_alarm(self) -> None:
        status, text = thc.build_message(NOW, True, GOOD_ITEMS, TASKS_OK, calpha=False, market_note="PRE_OPEN")
        self.assertEqual(status, "READY")
        self.assertIn("auto-starts 09:14", text)
        self.assertNotIn("NOT RUNNING", text)          # the old script's false alarm
        self.assertIn("not started yet", text)          # CAlpha not running at 09:10 is just informational
        self.assertIn("PAPER ONLY", text)

    def test_not_ready_when_token_fails_live_check(self) -> None:
        status, text = thc.build_message(NOW, False, GOOD_ITEMS, TASKS_OK, calpha=True, market_note="PRE_OPEN")
        self.assertEqual(status, "NOT READY")
        self.assertIn("live check FAILED", text)
        self.assertIn("🔴", text)

    def test_not_ready_when_supervisor_down_or_morning_task_missing(self) -> None:
        sup_down = {**GOOD_ITEMS, "Supervisor": {"level": "bad", "value": "silent 12 min"}}
        self.assertEqual(thc.build_message(NOW, True, sup_down, TASKS_OK, True, "x")[0], "NOT READY")
        no_task = {**TASKS_OK, "APlusOptionsScannerV3_MorningStart": None}
        self.assertEqual(thc.build_message(NOW, True, GOOD_ITEMS, no_task, True, "x")[0], "NOT READY")

    def test_warning_gives_check_status(self) -> None:
        warn = {**GOOD_ITEMS, "MWPL / ban data": {"level": "warn", "value": "empty", "detail": ""}}
        status, text = thc.build_message(NOW, True, warn, TASKS_OK, True, "x")
        self.assertEqual(status, "CHECK")
        self.assertIn("🟡", text)


if __name__ == "__main__":
    unittest.main()
