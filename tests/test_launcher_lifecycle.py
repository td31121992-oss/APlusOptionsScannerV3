from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherLifecycleTests(unittest.TestCase):
    def test_live_dashboard_launcher_detaches_python_and_returns(self) -> None:
        source = (ROOT / "run_live_pnl_dashboard.bat").read_text(encoding="utf-8")
        lowered = source.casefold()
        self.assertIn("netstat -ano -p tcp", lowered)
        self.assertIn('start "" /b "%python%" "%~dp0aplus_live_pnl_dashboard.py"', lowered)
        self.assertIn("exit /b 0", lowered)
        self.assertNotIn('"%~dp0.venv\\scripts\\python.exe" "%~dp0aplus_live_pnl_dashboard.py"', lowered)

    def test_scanner_launcher_waits_for_worker_and_propagates_exit_code(self) -> None:
        source = (ROOT / "run_intraday_movement.bat").read_text(encoding="utf-8").casefold()
        self.assertIn('"%python%" "%~dp0main.py" --intraday-movement', source)
        self.assertIn("set \"exitcode=%errorlevel%\"", source)
        self.assertIn("exit /b %exitcode%", source)


if __name__ == "__main__":
    unittest.main()
