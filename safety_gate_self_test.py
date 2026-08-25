from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from safety_gate import SafetyGateConfig, SafetyGateEngine


IST = ZoneInfo("Asia/Kolkata")


def _write_inputs(
    data_dir: Path,
    *,
    symbol: str = "HAL",
    event_today: bool = False,
    event_severity: str = "LOW",
    mwpl: float = 40.0,
    status: str = "SAFE",
) -> None:
    today = datetime.now(IST).date()
    safety = data_dir / "safety"
    safety.mkdir(parents=True, exist_ok=True)

    (safety / "nse_holidays.csv").write_text(
        "date,description\n"
        f"{(today + timedelta(days=9)).isoformat()},Self-test holiday\n",
        encoding="utf-8",
    )
    event_date = today if event_today else today + timedelta(days=60)
    (safety / "corporate_events.csv").write_text(
        "symbol,event_date,event_type,severity,as_of,source,notes\n"
        f"{symbol},{event_date.isoformat()},RESULTS,{event_severity},"
        f"{today.isoformat()},SELF_TEST,test\n",
        encoding="utf-8",
    )
    (safety / "mwpl_status.csv").write_text(
        "symbol,as_of,mwpl_utilization_percent,status,source,notes\n"
        f"{symbol},{today.isoformat()},{mwpl},{status},SELF_TEST,\n",
        encoding="utf-8",
    )
    (safety / "portfolio_state.json").write_text(
        json.dumps(
            {
                "as_of": today.isoformat(),
                "capital_override": 0,
                "available_balance": 0,
                "open_positions": 0,
                "open_total_risk": 0,
                "open_premium": 0,
                "realized_pnl_today": 0,
                "trades_today": 0,
                "consecutive_losses": 0,
            }
        ),
        encoding="utf-8",
    )


def main() -> int:
    now = datetime.now(IST)
    today = now.date()
    expiry = today + timedelta(days=30)
    contract = {
        "expiry": expiry.isoformat(),
        "quantity": 100,
        "limit_price": 100.0,
        "target1": 125.0,
        "total_risk": 1000.0,
        "total_premium": 10000.0,
        "spread_percent": 1.0,
    }
    funds = {
        "availabelBalance": 500000,
        "sodLimit": 500000,
        "utilizedAmount": 0,
    }

    with tempfile.TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        _write_inputs(data_dir)
        engine = SafetyGateEngine(
            SafetyGateConfig(mode="PAPER_OBSERVE"),
            data_dir=data_dir,
        )

        passed = engine.evaluate(
            symbol="HAL",
            option_contract=contract,
            now=now,
            fund_limits=funds,
            positions=[],
            fund_limits_available=True,
            positions_available=True,
        )
        assert passed.allowed and passed.decision == "PASS", passed.to_dict()

        expiry_day = engine.evaluate(
            symbol="HAL",
            option_contract={**contract, "expiry": today.isoformat()},
            now=now,
            fund_limits=funds,
            positions=[],
            fund_limits_available=True,
            positions_available=True,
        )
        assert not expiry_day.allowed
        assert any(
            "EXPIRY_SETTLEMENT" in item
            for item in expiry_day.block_reasons
        )

        _write_inputs(
            data_dir,
            event_today=True,
            event_severity="HIGH",
        )
        event = engine.evaluate(
            symbol="HAL",
            option_contract=contract,
            now=now,
            fund_limits=funds,
            positions=[],
            fund_limits_available=True,
            positions_available=True,
        )
        assert not event.allowed
        assert any(
            "CORPORATE_EVENT" in item
            for item in event.block_reasons
        )

        _write_inputs(data_dir, mwpl=96.0, status="FNO_BAN")
        ban = engine.evaluate(
            symbol="HAL",
            option_contract=contract,
            now=now,
            fund_limits=funds,
            positions=[],
            fund_limits_available=True,
            positions_available=True,
        )
        assert not ban.allowed
        assert any(
            "MWPL_FNO_BAN" in item
            for item in ban.block_reasons
        )

        _write_inputs(data_dir)
        cost = engine.evaluate(
            symbol="HAL",
            option_contract={**contract, "target1": 101.0},
            now=now,
            fund_limits=funds,
            positions=[],
            fund_limits_available=True,
            positions_available=True,
        )
        assert not cost.allowed
        assert any(
            "NET_COST_EXPECTANCY" in item
            for item in cost.block_reasons
        )

    with tempfile.TemporaryDirectory() as temporary:
        strict = SafetyGateEngine(
            SafetyGateConfig(mode="STRICT"),
            data_dir=Path(temporary),
        )
        missing = strict.evaluate(
            symbol="HAL",
            option_contract=contract,
            now=now,
        )
        assert not missing.allowed
        joined = " ".join(missing.block_reasons)
        for expected in (
            "EXPIRY_SETTLEMENT",
            "CORPORATE_EVENT",
            "MWPL_FNO_BAN",
            "PORTFOLIO_RISK",
        ):
            assert expected in joined, missing.to_dict()

    print("ALL_SAFETY_GATE_SELF_TESTS_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
