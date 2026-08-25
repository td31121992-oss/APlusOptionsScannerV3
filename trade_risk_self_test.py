from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from option_selector import OptionSelectionConfig
from safety_gate import SafetyGateConfig, SafetyGateEngine

IST = ZoneInfo("Asia/Kolkata")


def _write_inputs(data_dir: Path, symbol: str = "LTM") -> None:
    today = datetime.now(IST).date()
    safety = data_dir / "safety"
    safety.mkdir(parents=True, exist_ok=True)
    (safety / "nse_holidays.csv").write_text("date,description\n", encoding="utf-8")
    (safety / "corporate_events.csv").write_text(
        "symbol,event_date,event_type,severity,as_of,source,notes\n"
        f"{symbol},{(today + timedelta(days=60)).isoformat()},RESULTS,LOW,{today.isoformat()},SELF_TEST,\n",
        encoding="utf-8",
    )
    (safety / "mwpl_status.csv").write_text(
        "symbol,as_of,mwpl_utilization_percent,status,source,notes\n"
        f"{symbol},{today.isoformat()},40,SAFE,SELF_TEST,\n",
        encoding="utf-8",
    )
    (safety / "portfolio_state.json").write_text(
        json.dumps({
            "as_of": today.isoformat(),
            "capital_override": 0,
            "available_balance": 0,
            "open_positions": 0,
            "open_total_risk": 0,
            "open_premium": 0,
            "realized_pnl_today": 0,
            "trades_today": 0,
            "consecutive_losses": 0,
        }),
        encoding="utf-8",
    )


def main() -> int:
    cfg = OptionSelectionConfig()
    assert abs(cfg.option_stop_loss_percent - 10.0) < 1e-9, cfg
    safety_cfg = SafetyGateConfig(mode="PAPER_OBSERVE")
    assert abs(safety_cfg.trade_risk_percent - 10.0) < 1e-9, safety_cfg

    # User's example: Rs 30,000 trade capital -> Rs 3,000 risk budget.
    trade_capital = 30_000.0
    assert abs(trade_capital * safety_cfg.trade_risk_percent / 100.0 - 3_000.0) < 1e-9

    # Recreate today's LTM economics using the new 10% option risk.
    # Rs 165 x 150 = Rs 24,750 committed capital; 10% = Rs 2,475.
    ltm_contract = {
        "expiry": (datetime.now(IST).date() + timedelta(days=15)).isoformat(),
        "quantity": 150,
        "limit_price": 165.0,
        "target1": 181.5,
        "total_premium": 24_750.0,
        "total_risk": 2_475.0,
        "spread_percent": 1.0,
    }
    funds = {
        "availabelBalance": 500_000.0,
        "sodLimit": 500_000.0,
        "utilizedAmount": 0.0,
    }

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _write_inputs(data_dir)
        engine = SafetyGateEngine(safety_cfg, data_dir=data_dir)
        result = engine.evaluate(
            symbol="LTM",
            option_contract=ltm_contract,
            now=datetime.now(IST),
            fund_limits=funds,
            positions=[],
            fund_limits_available=True,
            positions_available=True,
        )
        portfolio = next(c for c in result.checks if c.name == "PORTFOLIO_RISK")
        assert portfolio.status.value in {"PASS", "WARN"}, result.to_dict()
        assert portfolio.details["risk_basis"] == "SELECTED_OPTION_PREMIUM"
        assert abs(portfolio.details["trade_capital_required"] - 24_750.0) < 0.01
        assert abs(portfolio.details["maximum_risk_per_trade"] - 2_475.0) < 0.01
        assert abs(portfolio.details["proposed_risk"] - 2_475.0) < 0.01

        # 11% risk must still be blocked by the 10% per-trade rule.
        too_risky = dict(ltm_contract)
        too_risky["total_risk"] = 2_722.50
        blocked = engine.evaluate(
            symbol="LTM",
            option_contract=too_risky,
            now=datetime.now(IST),
            fund_limits=funds,
            positions=[],
            fund_limits_available=True,
            positions_available=True,
        )
        assert not blocked.allowed, blocked.to_dict()
        assert any(
            "per-trade capital risk limit" in reason
            for reason in blocked.block_reasons
        ), blocked.to_dict()

    print("PASS: trade capital Rs 30,000 -> max risk Rs 3,000")
    print("PASS: LTM Rs 24,750 premium -> max/actual risk Rs 2,475")
    print("PASS: risk basis is selected option premium, not account capital")
    print("PASS: >10% trade-capital risk remains blocked")
    print("ALL PER-TRADE RISK SELF-TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
