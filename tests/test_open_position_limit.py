from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import safety_gate as sg

IST = ZoneInfo("Asia/Kolkata")
CONTRACT = {"total_risk": 1000.0, "total_premium": 10000.0}


def _check(open_positions: int, config: sg.SafetyGateConfig):
    with tempfile.TemporaryDirectory() as tmp:
        today = datetime.now(IST).date()
        Path(tmp, "portfolio_state.json").write_text(
            json.dumps({
                "as_of": today.isoformat(), "date": today.isoformat(), "mode": "PAPER_NATIVE",
                "open_positions": open_positions, "open_premium": 0, "open_total_risk": 0,
                "realized_pnl_today": 0, "trades_today": 0, "consecutive_losses": 0,
            }),
            encoding="utf-8",
        )
        engine = sg.SafetyGateEngine(config, data_dir=tmp)
        check, _ = engine._portfolio_check(
            option_contract=CONTRACT, fund_limits=None, positions=None,
            fund_limits_available=False, positions_available=False, today=today,
        )
        return check


class OpenPositionLimitTests(unittest.TestCase):
    def test_default_is_unlimited(self) -> None:
        self.assertEqual(sg.SafetyGateConfig().maximum_open_positions, 0)

    def test_many_open_positions_not_blocked_by_default(self) -> None:
        for count in (0, 2, 5, 12):
            check = _check(count, sg.SafetyGateConfig())
            self.assertNotIn("Maximum open-position count", check.message, f"open={count}: {check.message}")

    def test_explicit_cap_still_blocks(self) -> None:
        check = _check(2, sg.SafetyGateConfig(maximum_open_positions=2))
        self.assertEqual(getattr(check.status, "value", check.status), "BLOCK")
        self.assertIn("Maximum open-position count", check.message)

    def test_explicit_cap_allows_below_limit(self) -> None:
        check = _check(1, sg.SafetyGateConfig(maximum_open_positions=2))
        self.assertNotIn("Maximum open-position count", check.message)


if __name__ == "__main__":
    unittest.main()
