from __future__ import annotations

import json
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import safety_gate as sg
import opening_momentum_scanner as scanner

IST = ZoneInfo("Asia/Kolkata")
CONTRACT = {"total_risk": 1000.0, "total_premium": 10000.0}
BAD_DAY = {"realized_pnl_today": -50000.0, "consecutive_losses": 7}


def _gate_check(state_extra: dict, config: sg.SafetyGateConfig):
    with tempfile.TemporaryDirectory() as tmp:
        today = datetime.now(IST).date()
        state = {
            "as_of": today.isoformat(), "date": today.isoformat(), "mode": "PAPER_NATIVE",
            "open_positions": 0, "open_premium": 0, "open_total_risk": 0, "trades_today": 0,
        }
        state.update(state_extra)
        Path(tmp, "portfolio_state.json").write_text(json.dumps(state), encoding="utf-8")
        engine = sg.SafetyGateEngine(config, data_dir=tmp)
        check, _ = engine._portfolio_check(
            option_contract=CONTRACT, fund_limits=None, positions=None,
            fund_limits_available=False, positions_available=False, today=today,
        )
        return check


def _breaker(state_extra: dict, config: sg.SafetyGateConfig) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        now = datetime.now(IST)
        path = Path(tmp, "portfolio_state.json")
        state = {"mode": "PAPER_NATIVE", "date": now.date().isoformat(), "as_of": now.isoformat()}
        state.update(state_extra)
        path.write_text(json.dumps(state), encoding="utf-8")
        fake = types.SimpleNamespace(
            paper_portfolio_state_path=path,
            safety_gate=types.SimpleNamespace(config=config),
            paper_state_max_age_seconds=300,
            _as_ist=lambda dt: dt if dt.tzinfo else dt.replace(tzinfo=IST),
        )
        return scanner.OpeningMomentumScanner._paper_native_circuit_breaker(fake, now)


class LossLimitTests(unittest.TestCase):
    def test_defaults_are_off(self) -> None:
        cfg = sg.SafetyGateConfig()
        self.assertEqual(cfg.maximum_daily_loss_percent, 0.0)
        self.assertEqual(cfg.maximum_consecutive_losses, 0)

    def test_config_from_env_loads_with_new_defaults(self) -> None:
        cfg = sg.SafetyGateConfig.from_env()   # must not raise on the 0.0 daily-loss default
        self.assertEqual(cfg.maximum_daily_loss_percent, 0.0)

    def test_gate_does_not_block_after_big_loss_and_losing_streak(self) -> None:
        check = _gate_check(BAD_DAY, sg.SafetyGateConfig())
        self.assertNotIn("daily loss", check.message.lower())
        self.assertNotIn("cooling-off", check.message.lower())

    def test_gate_explicit_limits_still_block(self) -> None:
        cfg = sg.SafetyGateConfig(maximum_daily_loss_percent=1.5, maximum_consecutive_losses=2)
        check = _gate_check(BAD_DAY, cfg)
        self.assertEqual(getattr(check.status, "value", check.status), "BLOCK")
        self.assertIn("daily loss", check.message.lower())
        self.assertIn("cooling-off", check.message.lower())

    def test_breaker_does_not_block_by_default(self) -> None:
        result = _breaker(BAD_DAY, sg.SafetyGateConfig())
        self.assertFalse(result["blocked"], result["reasons"])

    def test_breaker_explicit_limits_still_block(self) -> None:
        cfg = sg.SafetyGateConfig(maximum_daily_loss_percent=1.5, maximum_consecutive_losses=2)
        result = _breaker(BAD_DAY, cfg)
        self.assertTrue(result["blocked"])
        text = " ".join(result["reasons"])
        self.assertIn("DAILY_LOSS_LIMIT", text)
        self.assertIn("CONSECUTIVE_LOSS_LIMIT", text)


class PremiumCapTests(unittest.TestCase):
    HEAVY = {"open_premium": 400000.0, "realized_pnl_today": 0.0, "consecutive_losses": 0}

    def test_default_has_no_premium_cap(self) -> None:
        self.assertEqual(sg.SafetyGateConfig().maximum_total_premium_percent, 0.0)
        cfg = sg.SafetyGateConfig.from_env()            # the 0.0 default must load (env minimum lowered to 0)
        self.assertEqual(cfg.maximum_total_premium_percent, 0.0)

    def test_large_deployed_premium_not_blocked_by_default(self) -> None:
        check = _gate_check(self.HEAVY, sg.SafetyGateConfig())
        self.assertNotIn("premium", check.message.lower())

    def test_explicit_cap_still_blocks(self) -> None:
        check = _gate_check(self.HEAVY, sg.SafetyGateConfig(maximum_total_premium_percent=20.0))
        self.assertEqual(getattr(check.status, "value", check.status), "BLOCK")
        self.assertIn("premium", check.message.lower())


if __name__ == "__main__":
    unittest.main()
