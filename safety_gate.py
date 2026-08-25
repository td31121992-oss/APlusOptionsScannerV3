"""
Stock-option pre-trade safety gates for APlus Options Scanner V3.

The engine is intentionally broker-order agnostic.  It evaluates a selected
long stock-option contract before a paper trade plan or recommendation is
published.  It never places, modifies, or cancels an order.

Five gates are implemented:
1. Expiry / physical-settlement proximity.
2. Corporate event / corporate-action calendar.
3. MWPL / F&O ban status.
4. Per-trade capital risk plus account-level safety limits.
5. Estimated round-trip costs and net-reward expectancy.

External event and MWPL inputs are read from local CSV files.  In
PAPER_OBSERVE mode missing/stale external data becomes a warning.  In STRICT
mode it blocks the candidate.  This prevents silent claims that live NSE event
or MWPL data was verified when it was not.
"""

from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


class GateStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SafetyGateConfig:
    enabled: bool = True
    mode: str = "PAPER_OBSERVE"

    minimum_trading_dte: int = 4
    mandatory_intraday_exit_time: str = "15:15"

    corporate_event_lookahead_days: int = 2
    corporate_event_lookback_days: int = 0
    corporate_event_max_age_days: int = 7
    block_event_severities: tuple[str, ...] = ("HIGH", "CRITICAL")

    mwpl_elevated_percent: float = 60.0
    mwpl_block_percent: float = 80.0
    mwpl_ban_percent: float = 95.0
    mwpl_max_age_days: int = 2

    fallback_account_capital: float = 500_000.0
    trade_risk_percent: float = 10.0
    maximum_daily_loss_percent: float = 1.50
    maximum_open_positions: int = 2
    maximum_total_premium_percent: float = 20.0
    maximum_trades_per_day: int = 0  # 0 = unlimited; quality/risk gates decide
    maximum_consecutive_losses: int = 2
    available_balance_buffer_percent: float = 5.0
    portfolio_state_max_age_days: int = 0

    brokerage_per_executed_order: float = 20.0
    exchange_transaction_charge_percent: float = 0.003
    sebi_turnover_fee_percent: float = 0.0001
    ipft_other_charge_percent: float = 0.0
    gst_percent: float = 18.0
    option_stt_sell_percent: float = 0.15
    option_stamp_buy_percent: float = 0.003
    execution_impact_percent_per_side: float = 0.10
    minimum_net_reward_cost_multiple: float = 2.0
    minimum_net_reward_risk_ratio: float = 0.50

    @classmethod
    def from_env(cls) -> "SafetyGateConfig":
        defaults = cls()
        mode = os.getenv("APLUS_SAFETY_MODE", defaults.mode).strip().upper()
        if mode not in {"PAPER_OBSERVE", "STRICT"}:
            raise ValueError(
                "APLUS_SAFETY_MODE must be PAPER_OBSERVE or STRICT"
            )
        return cls(
            enabled=_env_bool("APLUS_SAFETY_ENABLED", defaults.enabled),
            mode=mode,
            minimum_trading_dte=_env_int(
                "APLUS_SAFETY_MIN_TRADING_DTE",
                defaults.minimum_trading_dte,
                minimum=0,
            ),
            mandatory_intraday_exit_time=os.getenv(
                "APLUS_SAFETY_INTRADAY_EXIT_TIME",
                defaults.mandatory_intraday_exit_time,
            ).strip(),
            corporate_event_lookahead_days=_env_int(
                "APLUS_SAFETY_EVENT_LOOKAHEAD_DAYS",
                defaults.corporate_event_lookahead_days,
                minimum=0,
            ),
            corporate_event_lookback_days=_env_int(
                "APLUS_SAFETY_EVENT_LOOKBACK_DAYS",
                defaults.corporate_event_lookback_days,
                minimum=0,
            ),
            corporate_event_max_age_days=_env_int(
                "APLUS_SAFETY_EVENT_MAX_AGE_DAYS",
                defaults.corporate_event_max_age_days,
                minimum=0,
            ),
            block_event_severities=tuple(
                item.strip().upper()
                for item in os.getenv(
                    "APLUS_SAFETY_BLOCK_EVENT_SEVERITIES",
                    ",".join(defaults.block_event_severities),
                ).split(",")
                if item.strip()
            ),
            mwpl_elevated_percent=_env_float(
                "APLUS_SAFETY_MWPL_ELEVATED_PERCENT",
                defaults.mwpl_elevated_percent,
                minimum=0.0,
            ),
            mwpl_block_percent=_env_float(
                "APLUS_SAFETY_MWPL_BLOCK_PERCENT",
                defaults.mwpl_block_percent,
                minimum=0.0,
            ),
            mwpl_ban_percent=_env_float(
                "APLUS_SAFETY_MWPL_BAN_PERCENT",
                defaults.mwpl_ban_percent,
                minimum=0.0,
            ),
            mwpl_max_age_days=_env_int(
                "APLUS_SAFETY_MWPL_MAX_AGE_DAYS",
                defaults.mwpl_max_age_days,
                minimum=0,
            ),
            fallback_account_capital=_env_float(
                "APLUS_SAFETY_ACCOUNT_CAPITAL",
                defaults.fallback_account_capital,
                minimum=1.0,
            ),
            trade_risk_percent=_env_float(
                "APLUS_SAFETY_TRADE_RISK_PERCENT",
                defaults.trade_risk_percent,
                minimum=0.01,
            ),
            maximum_daily_loss_percent=_env_float(
                "APLUS_SAFETY_MAX_DAILY_LOSS_PERCENT",
                defaults.maximum_daily_loss_percent,
                minimum=0.01,
            ),
            maximum_open_positions=_env_int(
                "APLUS_SAFETY_MAX_OPEN_POSITIONS",
                defaults.maximum_open_positions,
                minimum=0,
            ),
            maximum_total_premium_percent=_env_float(
                "APLUS_SAFETY_MAX_TOTAL_PREMIUM_PERCENT",
                defaults.maximum_total_premium_percent,
                minimum=0.01,
            ),
            maximum_trades_per_day=_env_int(
                "APLUS_SAFETY_MAX_TRADES_PER_DAY",
                defaults.maximum_trades_per_day,
                minimum=0,
            ),
            maximum_consecutive_losses=_env_int(
                "APLUS_SAFETY_MAX_CONSECUTIVE_LOSSES",
                defaults.maximum_consecutive_losses,
                minimum=0,
            ),
            available_balance_buffer_percent=_env_float(
                "APLUS_SAFETY_BALANCE_BUFFER_PERCENT",
                defaults.available_balance_buffer_percent,
                minimum=0.0,
            ),
            portfolio_state_max_age_days=_env_int(
                "APLUS_SAFETY_PORTFOLIO_STATE_MAX_AGE_DAYS",
                defaults.portfolio_state_max_age_days,
                minimum=0,
            ),
            brokerage_per_executed_order=_env_float(
                "APLUS_COST_BROKERAGE_PER_ORDER",
                defaults.brokerage_per_executed_order,
                minimum=0.0,
            ),
            exchange_transaction_charge_percent=_env_float(
                "APLUS_COST_EXCHANGE_PERCENT",
                defaults.exchange_transaction_charge_percent,
                minimum=0.0,
            ),
            sebi_turnover_fee_percent=_env_float(
                "APLUS_COST_SEBI_PERCENT",
                defaults.sebi_turnover_fee_percent,
                minimum=0.0,
            ),
            ipft_other_charge_percent=_env_float(
                "APLUS_COST_IPFT_OTHER_PERCENT",
                defaults.ipft_other_charge_percent,
                minimum=0.0,
            ),
            gst_percent=_env_float(
                "APLUS_COST_GST_PERCENT",
                defaults.gst_percent,
                minimum=0.0,
            ),
            option_stt_sell_percent=_env_float(
                "APLUS_COST_OPTION_STT_SELL_PERCENT",
                defaults.option_stt_sell_percent,
                minimum=0.0,
            ),
            option_stamp_buy_percent=_env_float(
                "APLUS_COST_OPTION_STAMP_BUY_PERCENT",
                defaults.option_stamp_buy_percent,
                minimum=0.0,
            ),
            execution_impact_percent_per_side=_env_float(
                "APLUS_COST_EXECUTION_IMPACT_PERCENT_PER_SIDE",
                defaults.execution_impact_percent_per_side,
                minimum=0.0,
            ),
            minimum_net_reward_cost_multiple=_env_float(
                "APLUS_SAFETY_MIN_NET_REWARD_COST_MULTIPLE",
                defaults.minimum_net_reward_cost_multiple,
                minimum=0.0,
            ),
            minimum_net_reward_risk_ratio=_env_float(
                "APLUS_SAFETY_MIN_NET_REWARD_RISK_RATIO",
                defaults.minimum_net_reward_risk_ratio,
                minimum=0.0,
            ),
        )

    @property
    def strict(self) -> bool:
        return self.mode == "STRICT"


@dataclass(slots=True)
class GateCheck:
    name: str
    status: GateStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(slots=True)
class SafetyGateResult:
    symbol: str
    evaluated_at: str
    mode: str
    allowed: bool
    decision: str
    checks: list[GateCheck] = field(default_factory=list)
    block_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    account_capital: float = 0.0
    available_balance: float = 0.0
    open_positions: int = 0
    realized_pnl_today: float = 0.0
    estimated_round_trip_cost: float = 0.0
    expected_gross_reward: float = 0.0
    expected_net_reward: float = 0.0
    net_reward_cost_multiple: float = 0.0
    net_reward_risk_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "evaluated_at": self.evaluated_at,
            "mode": self.mode,
            "allowed": self.allowed,
            "decision": self.decision,
            "checks": [item.to_dict() for item in self.checks],
            "block_reasons": list(self.block_reasons),
            "warnings": list(self.warnings),
            "account_capital": round(self.account_capital, 2),
            "available_balance": round(self.available_balance, 2),
            "open_positions": int(self.open_positions),
            "realized_pnl_today": round(self.realized_pnl_today, 2),
            "estimated_round_trip_cost": round(
                self.estimated_round_trip_cost, 2
            ),
            "expected_gross_reward": round(
                self.expected_gross_reward, 2
            ),
            "expected_net_reward": round(self.expected_net_reward, 2),
            "net_reward_cost_multiple": round(
                self.net_reward_cost_multiple, 2
            ),
            "net_reward_risk_ratio": round(
                self.net_reward_risk_ratio, 2
            ),
        }


class SafetyGateEngine:
    """Evaluate a selected long stock option against pre-trade safety gates."""

    def __init__(
        self,
        config: SafetyGateConfig | None = None,
        *,
        data_dir: str | Path = "data",
    ) -> None:
        self.config = config or SafetyGateConfig.from_env()
        self.data_dir = Path(data_dir)
        self.safety_dir = self.data_dir / "safety"
        self.safety_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(
        cls,
        *,
        data_dir: str | Path = "data",
    ) -> "SafetyGateEngine":
        return cls(SafetyGateConfig.from_env(), data_dir=data_dir)

    def evaluate(
        self,
        *,
        symbol: str,
        option_contract: Any,
        now: datetime | None = None,
        fund_limits: Mapping[str, Any] | None = None,
        positions: Sequence[Mapping[str, Any]] | None = None,
        fund_limits_available: bool | None = None,
        positions_available: bool | None = None,
        candidate_context: Mapping[str, Any] | None = None,
    ) -> SafetyGateResult:
        current = _as_ist(now or datetime.now(IST))
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol is required")

        result = SafetyGateResult(
            symbol=normalized_symbol,
            evaluated_at=current.isoformat(),
            mode=self.config.mode,
            allowed=True,
            decision="PASS",
        )

        if not self.config.enabled:
            result.checks.append(
                GateCheck(
                    "SAFETY_ENGINE",
                    GateStatus.WARN,
                    "Safety gates are disabled by configuration",
                )
            )
            result.warnings.append("Safety gates are disabled")
            result.decision = "WARN"
            return result

        result.checks.append(
            self._expiry_check(option_contract, current)
        )
        result.checks.append(
            self._corporate_event_check(normalized_symbol, current.date())
        )
        result.checks.append(
            self._mwpl_check(normalized_symbol, current.date())
        )

        portfolio_check, portfolio_metrics = self._portfolio_check(
            option_contract=option_contract,
            fund_limits=fund_limits,
            positions=positions,
            fund_limits_available=fund_limits_available,
            positions_available=positions_available,
            today=current.date(),
        )
        result.checks.append(portfolio_check)
        result.account_capital = portfolio_metrics["account_capital"]
        result.available_balance = portfolio_metrics["available_balance"]
        result.open_positions = int(portfolio_metrics["open_positions"])
        result.realized_pnl_today = portfolio_metrics[
            "realized_pnl_today"
        ]

        cost_check, cost_metrics = self._cost_expectancy_check(
            option_contract=option_contract,
            candidate_context=candidate_context,
        )
        result.checks.append(cost_check)
        result.estimated_round_trip_cost = cost_metrics[
            "estimated_round_trip_cost"
        ]
        result.expected_gross_reward = cost_metrics[
            "expected_gross_reward"
        ]
        result.expected_net_reward = cost_metrics["expected_net_reward"]
        result.net_reward_cost_multiple = cost_metrics[
            "net_reward_cost_multiple"
        ]
        result.net_reward_risk_ratio = cost_metrics[
            "net_reward_risk_ratio"
        ]

        for check in result.checks:
            if check.status == GateStatus.BLOCK:
                result.block_reasons.append(
                    f"{check.name}: {check.message}"
                )
            elif check.status in {GateStatus.WARN, GateStatus.UNKNOWN}:
                result.warnings.append(
                    f"{check.name}: {check.message}"
                )

        result.allowed = not result.block_reasons
        if not result.allowed:
            result.decision = "BLOCK"
        elif result.warnings:
            result.decision = "WARN"
        else:
            result.decision = "PASS"
        return result

    def _expiry_check(
        self,
        option_contract: Any,
        now: datetime,
    ) -> GateCheck:
        expiry = _parse_date(_value(option_contract, "expiry"))
        if expiry is None:
            return self._unknown_or_block(
                "EXPIRY_SETTLEMENT",
                "Option expiry is missing or invalid",
            )

        holidays = self._load_holidays()
        trading_dte = _trading_days_between(
            now.date(), expiry, holidays=holidays
        )
        details = {
            "expiry": expiry.isoformat(),
            "calendar_dte": (expiry - now.date()).days,
            "trading_dte": trading_dte,
            "minimum_trading_dte": self.config.minimum_trading_dte,
            "mandatory_intraday_exit_time": (
                self.config.mandatory_intraday_exit_time
            ),
            "holiday_calendar_rows": len(holidays),
        }

        if expiry < now.date():
            return GateCheck(
                "EXPIRY_SETTLEMENT",
                GateStatus.BLOCK,
                "Selected option contract is already expired",
                details,
            )
        if expiry == now.date():
            return GateCheck(
                "EXPIRY_SETTLEMENT",
                GateStatus.BLOCK,
                "Fresh stock-option entry is blocked on expiry day",
                details,
            )
        if trading_dte < self.config.minimum_trading_dte:
            return GateCheck(
                "EXPIRY_SETTLEMENT",
                GateStatus.BLOCK,
                "Contract is too close to stock-option expiry and physical-settlement risk",
                details,
            )

        message = (
            f"Expiry is {trading_dte} trading day(s) away; "
            f"intraday exit target {self.config.mandatory_intraday_exit_time}"
        )
        if not holidays:
            return GateCheck(
                "EXPIRY_SETTLEMENT",
                (
                    GateStatus.BLOCK
                    if self.config.strict
                    else GateStatus.WARN
                ),
                message + "; no exchange-holiday file was supplied",
                details,
            )
        return GateCheck(
            "EXPIRY_SETTLEMENT",
            GateStatus.PASS,
            message,
            details,
        )

    def _corporate_event_check(
        self,
        symbol: str,
        today: date,
    ) -> GateCheck:
        path = self.safety_dir / "corporate_events.csv"
        rows = _read_csv(path)
        if not rows:
            return self._unknown_or_block(
                "CORPORATE_EVENT",
                "Corporate-event calendar has no usable rows",
                {"path": str(path)},
            )

        relevant: list[dict[str, Any]] = []
        newest_source_date: date | None = None
        for row in rows:
            if str(row.get("symbol", "")).strip().upper() != symbol:
                continue
            event_date = _parse_date(row.get("event_date"))
            if event_date is None:
                continue
            source_as_of = _parse_date(
                row.get("as_of") or row.get("source_date")
            )
            if source_as_of and (
                newest_source_date is None
                or source_as_of > newest_source_date
            ):
                newest_source_date = source_as_of
            delta = (event_date - today).days
            if (
                -self.config.corporate_event_lookback_days
                <= delta
                <= self.config.corporate_event_lookahead_days
            ):
                relevant.append(
                    {
                        "event_date": event_date.isoformat(),
                        "event_type": str(
                            row.get("event_type", "UNKNOWN")
                        ).strip().upper(),
                        "severity": str(
                            row.get("severity", "HIGH")
                        ).strip().upper(),
                        "source": str(row.get("source", "")).strip(),
                        "notes": str(row.get("notes", "")).strip(),
                    }
                )

        stale = (
            newest_source_date is not None
            and (today - newest_source_date).days
            > self.config.corporate_event_max_age_days
        )
        if stale:
            return self._unknown_or_block(
                "CORPORATE_EVENT",
                "Corporate-event data is stale",
                {
                    "path": str(path),
                    "newest_source_date": newest_source_date.isoformat(),
                    "max_age_days": self.config.corporate_event_max_age_days,
                },
            )

        blocking = [
            item
            for item in relevant
            if item["severity"] in self.config.block_event_severities
        ]
        if blocking:
            return GateCheck(
                "CORPORATE_EVENT",
                GateStatus.BLOCK,
                "Blocking corporate event is inside the configured risk window",
                {"events": blocking, "path": str(path)},
            )
        if relevant:
            return GateCheck(
                "CORPORATE_EVENT",
                GateStatus.WARN,
                "Non-blocking corporate event is inside the risk window",
                {"events": relevant, "path": str(path)},
            )
        return GateCheck(
            "CORPORATE_EVENT",
            GateStatus.PASS,
            "No listed corporate event is inside the configured risk window",
            {"path": str(path)},
        )

    def _mwpl_check(self, symbol: str, today: date) -> GateCheck:
        path = self.safety_dir / "mwpl_status.csv"
        rows = _read_csv(path)
        matching = [
            row
            for row in rows
            if str(row.get("symbol", "")).strip().upper() == symbol
        ]
        if not matching:
            return self._unknown_or_block(
                "MWPL_FNO_BAN",
                "No MWPL/F&O-ban row is available for the symbol",
                {"path": str(path)},
            )

        def row_date(row: Mapping[str, Any]) -> date:
            return _parse_date(row.get("as_of")) or date.min

        latest = max(matching, key=row_date)
        as_of = _parse_date(latest.get("as_of"))
        if as_of is None:
            return self._unknown_or_block(
                "MWPL_FNO_BAN",
                "MWPL row has no valid as_of date",
                {"path": str(path)},
            )
        age_days = (today - as_of).days
        if age_days < 0 or age_days > self.config.mwpl_max_age_days:
            return self._unknown_or_block(
                "MWPL_FNO_BAN",
                "MWPL/F&O-ban data is stale or future-dated",
                {
                    "path": str(path),
                    "as_of": as_of.isoformat(),
                    "age_days": age_days,
                    "max_age_days": self.config.mwpl_max_age_days,
                },
            )

        status = str(latest.get("status", "")).strip().upper()
        utilization = _number(
            latest.get("mwpl_utilization_percent"), default=-1.0
        )
        details = {
            "path": str(path),
            "as_of": as_of.isoformat(),
            "status": status or "UNKNOWN",
            "mwpl_utilization_percent": (
                utilization if utilization >= 0 else None
            ),
            "elevated_threshold": self.config.mwpl_elevated_percent,
            "block_threshold": self.config.mwpl_block_percent,
            "ban_threshold": self.config.mwpl_ban_percent,
            "source": str(latest.get("source", "")).strip(),
        }

        if status in {"FNO_BAN", "BAN", "BANNED"}:
            return GateCheck(
                "MWPL_FNO_BAN",
                GateStatus.BLOCK,
                "Symbol is marked in the F&O ban period",
                details,
            )
        if utilization >= self.config.mwpl_ban_percent:
            return GateCheck(
                "MWPL_FNO_BAN",
                GateStatus.BLOCK,
                "MWPL utilization is at or above the ban threshold",
                details,
            )
        if utilization >= self.config.mwpl_block_percent or status in {
            "MWPL_HIGH",
            "HIGH",
        }:
            return GateCheck(
                "MWPL_FNO_BAN",
                GateStatus.BLOCK,
                "MWPL utilization is too high for a new option entry",
                details,
            )
        if utilization >= self.config.mwpl_elevated_percent or status in {
            "MWPL_ELEVATED",
            "ELEVATED",
        }:
            return GateCheck(
                "MWPL_FNO_BAN",
                GateStatus.WARN,
                "MWPL utilization is elevated",
                details,
            )
        if utilization < 0 and status not in {"MWPL_SAFE", "SAFE"}:
            return self._unknown_or_block(
                "MWPL_FNO_BAN",
                "MWPL row has neither a usable utilization nor SAFE status",
                details,
            )
        return GateCheck(
            "MWPL_FNO_BAN",
            GateStatus.PASS,
            "MWPL/F&O-ban status is within configured limits",
            details,
        )

    def _portfolio_check(
        self,
        *,
        option_contract: Any,
        fund_limits: Mapping[str, Any] | None,
        positions: Sequence[Mapping[str, Any]] | None,
        fund_limits_available: bool | None,
        positions_available: bool | None,
        today: date,
    ) -> tuple[GateCheck, dict[str, float]]:
        state = self._load_portfolio_state()
        fund_limits = dict(fund_limits or {})
        positions = list(positions or [])
        live_fund_limits_supplied = (
            bool(fund_limits)
            if fund_limits_available is None
            else bool(fund_limits_available)
        )
        live_positions_supplied = (
            bool(positions)
            if positions_available is None
            else bool(positions_available)
        )

        available_balance = _first_number(
            fund_limits,
            ("availabelBalance", "availableBalance", "available_balance"),
            default=_number(state.get("available_balance"), 0.0),
        )
        sod_limit = _first_number(
            fund_limits,
            ("sodLimit", "sod_limit"),
            default=0.0,
        )
        utilized_amount = _first_number(
            fund_limits,
            ("utilizedAmount", "utilized_amount"),
            default=0.0,
        )
        state_as_of = _parse_date(state.get("as_of"))
        state_age_days = (
            (today - state_as_of).days
            if state_as_of is not None
            else None
        )
        state_fresh = (
            state_as_of is not None
            and state_age_days is not None
            and 0 <= state_age_days
            <= self.config.portfolio_state_max_age_days
        )

        capital_override = _number(
            state.get("capital_override"), default=0.0
        )
        if capital_override > 0:
            account_capital = capital_override
        elif sod_limit > 0:
            account_capital = sod_limit
        elif available_balance + utilized_amount > 0:
            account_capital = available_balance + utilized_amount
        else:
            account_capital = self.config.fallback_account_capital

        live_open = [
            row
            for row in positions
            if int(_number(row.get("netQty"), 0.0)) != 0
        ]
        open_positions = max(
            len(live_open),
            int(_number(state.get("open_positions"), 0.0)),
        )
        paper_native_state = (
            str(state.get("mode") or "").strip().upper() == "PAPER_NATIVE"
        )
        realized_pnl = (
            _number(state.get("realized_pnl_today"), 0.0)
            if paper_native_state
            else (
                sum(_number(row.get("realizedProfit"), 0.0) for row in positions)
                if positions
                else _number(state.get("realized_pnl_today"), 0.0)
            )
        )
        open_total_risk = _number(
            state.get("open_total_risk"), default=0.0
        )
        live_open_premium = sum(
            max(
                0.0,
                _number(row.get("dayBuyValue"), 0.0)
                - _number(row.get("daySellValue"), 0.0),
            )
            for row in live_open
            if str(row.get("exchangeSegment", "")).upper()
            in {"NSE_FNO", "BSE_FNO"}
        )
        open_premium = max(
            live_open_premium,
            _number(state.get("open_premium"), 0.0),
        )
        trades_today = int(_number(state.get("trades_today"), 0.0))
        consecutive_losses = int(
            _number(state.get("consecutive_losses"), 0.0)
        )

        proposed_risk = _number(
            _value(option_contract, "total_risk"), default=0.0
        )
        proposed_premium = _number(
            _value(option_contract, "total_premium"), default=0.0
        )
        # Long CE/PE trades pay the option premium upfront, so the capital
        # committed to this trade is the selected option premium itself.
        # Per-trade risk is therefore derived from THIS trade's capital, not
        # from total account/portfolio capital.
        trade_capital_required = proposed_premium
        maximum_risk = (
            trade_capital_required
            * self.config.trade_risk_percent
            / 100.0
        )
        proposed_risk_percent_of_trade = (
            proposed_risk / trade_capital_required * 100.0
            if trade_capital_required > 0
            else 0.0
        )
        maximum_daily_loss = (
            account_capital
            * self.config.maximum_daily_loss_percent
            / 100.0
        )
        maximum_total_premium = (
            account_capital
            * self.config.maximum_total_premium_percent
            / 100.0
        )
        required_balance = proposed_premium * (
            1.0 + self.config.available_balance_buffer_percent / 100.0
        )

        details = {
            "account_capital": round(account_capital, 2),
            "available_balance": round(available_balance, 2),
            "open_positions": open_positions,
            "realized_pnl_today": round(realized_pnl, 2),
            "open_total_risk": round(open_total_risk, 2),
            "open_premium": round(open_premium, 2),
            "trades_today": trades_today,
            "consecutive_losses": consecutive_losses,
            "proposed_risk": round(proposed_risk, 2),
            "proposed_premium": round(proposed_premium, 2),
            "trade_capital_required": round(trade_capital_required, 2),
            "trade_risk_percent_limit": round(self.config.trade_risk_percent, 4),
            "proposed_risk_percent_of_trade_capital": round(
                proposed_risk_percent_of_trade, 4
            ),
            "risk_basis": "SELECTED_OPTION_PREMIUM",
            "maximum_risk_per_trade": round(maximum_risk, 2),
            "maximum_daily_loss": round(maximum_daily_loss, 2),
            "maximum_total_premium": round(maximum_total_premium, 2),
            "required_balance_with_buffer": round(required_balance, 2),
            "live_fund_limits_supplied": live_fund_limits_supplied,
            "live_positions_supplied": live_positions_supplied,
            "portfolio_state_as_of": (
                state_as_of.isoformat() if state_as_of else None
            ),
            "portfolio_state_age_days": state_age_days,
            "portfolio_state_max_age_days": (
                self.config.portfolio_state_max_age_days
            ),
            "portfolio_state_fresh": state_fresh,
        }

        data_issues: list[str] = []
        if not paper_native_state:
            if not live_fund_limits_supplied:
                data_issues.append("live fund limits unavailable")
            if not live_positions_supplied:
                data_issues.append("live positions unavailable")
        if not state_fresh:
            data_issues.append(
                "portfolio_state.json is missing, future-dated, or stale"
            )

        reasons: list[str] = []
        if self.config.strict:
            reasons.extend(data_issues)
        if proposed_risk <= 0 or proposed_premium <= 0:
            reasons.append("Selected option has invalid premium or risk")
        # Small tolerance avoids a floating-point rounding block when risk is
        # exactly equal to the configured percentage of trade capital.
        if proposed_risk > maximum_risk + 0.01:
            reasons.append(
                "Proposed option risk exceeds per-trade capital risk limit"
            )
        if realized_pnl <= -maximum_daily_loss:
            reasons.append("Maximum daily loss has been reached")
        if open_positions >= self.config.maximum_open_positions:
            reasons.append("Maximum open-position count has been reached")
        if open_premium + proposed_premium > maximum_total_premium:
            reasons.append("Total deployed option premium would exceed limit")
        if self.config.maximum_trades_per_day > 0 and trades_today >= self.config.maximum_trades_per_day:
            reasons.append("Maximum trades per day has been reached")
        if consecutive_losses >= self.config.maximum_consecutive_losses:
            reasons.append("Consecutive-loss cooling-off threshold reached")
        if available_balance > 0 and available_balance < required_balance:
            reasons.append("Available balance is insufficient with safety buffer")

        metrics = {
            "account_capital": account_capital,
            "available_balance": available_balance,
            "open_positions": float(open_positions),
            "realized_pnl_today": realized_pnl,
        }
        if reasons:
            return (
                GateCheck(
                    "PORTFOLIO_RISK",
                    GateStatus.BLOCK,
                    "; ".join(reasons),
                    details,
                ),
                metrics,
            )

        warnings: list[str] = list(data_issues)
        if open_positions and open_total_risk <= 0:
            warnings.append("open-position risk is not recorded in portfolio_state.json")
        if warnings:
            return (
                GateCheck(
                    "PORTFOLIO_RISK",
                    GateStatus.WARN,
                    "; ".join(warnings),
                    details,
                ),
                metrics,
            )
        return (
            GateCheck(
                "PORTFOLIO_RISK",
                GateStatus.PASS,
                "Per-trade risk and portfolio safeguards pass",
                details,
            ),
            metrics,
        )

    def _cost_expectancy_check(
        self,
        *,
        option_contract: Any,
        candidate_context: Mapping[str, Any] | None,
    ) -> tuple[GateCheck, dict[str, float]]:
        quantity = int(_number(_value(option_contract, "quantity"), 0.0))
        entry = _number(_value(option_contract, "limit_price"), 0.0)
        target1 = _number(_value(option_contract, "target1"), 0.0)
        total_risk = _number(_value(option_contract, "total_risk"), 0.0)
        spread_percent = _number(
            _value(option_contract, "spread_percent"), 0.0
        )

        if quantity <= 0 or entry <= 0 or target1 <= entry:
            metrics = {
                "estimated_round_trip_cost": 0.0,
                "expected_gross_reward": 0.0,
                "expected_net_reward": 0.0,
                "net_reward_cost_multiple": 0.0,
                "net_reward_risk_ratio": 0.0,
            }
            return (
                GateCheck(
                    "NET_COST_EXPECTANCY",
                    GateStatus.BLOCK,
                    "Option quantity, entry, or target is invalid",
                    {
                        "quantity": quantity,
                        "entry": entry,
                        "target1": target1,
                    },
                ),
                metrics,
            )

        buy_turnover = entry * quantity
        sell_turnover = target1 * quantity
        turnover = buy_turnover + sell_turnover

        brokerage = self.config.brokerage_per_executed_order * 2.0
        exchange = (
            turnover
            * self.config.exchange_transaction_charge_percent
            / 100.0
        )
        sebi = turnover * self.config.sebi_turnover_fee_percent / 100.0
        ipft_other = (
            turnover * self.config.ipft_other_charge_percent / 100.0
        )
        gst = (
            brokerage + exchange + sebi + ipft_other
        ) * self.config.gst_percent / 100.0
        stt = (
            sell_turnover
            * self.config.option_stt_sell_percent
            / 100.0
        )
        stamp = (
            buy_turnover
            * self.config.option_stamp_buy_percent
            / 100.0
        )
        effective_impact_percent = max(
            self.config.execution_impact_percent_per_side,
            spread_percent / 2.0,
        )
        execution_impact = (
            turnover * effective_impact_percent / 100.0
        )
        estimated_cost = (
            brokerage
            + exchange
            + sebi
            + ipft_other
            + gst
            + stt
            + stamp
            + execution_impact
        )
        gross_reward = (target1 - entry) * quantity
        net_reward = gross_reward - estimated_cost
        cost_multiple = (
            net_reward / estimated_cost
            if estimated_cost > 0
            else math.inf
        )
        net_rr = net_reward / total_risk if total_risk > 0 else 0.0

        details = {
            "quantity": quantity,
            "entry_price": round(entry, 2),
            "target1_price": round(target1, 2),
            "buy_turnover": round(buy_turnover, 2),
            "sell_turnover": round(sell_turnover, 2),
            "brokerage": round(brokerage, 2),
            "exchange_transaction_charges": round(exchange, 2),
            "sebi_turnover_fee": round(sebi, 2),
            "ipft_other_charges": round(ipft_other, 2),
            "gst": round(gst, 2),
            "stt_sell": round(stt, 2),
            "stamp_duty_buy": round(stamp, 2),
            "execution_impact": round(execution_impact, 2),
            "effective_execution_impact_percent": round(
                effective_impact_percent, 4
            ),
            "estimated_round_trip_cost": round(estimated_cost, 2),
            "expected_gross_reward": round(gross_reward, 2),
            "expected_net_reward": round(net_reward, 2),
            "net_reward_cost_multiple": round(cost_multiple, 2),
            "net_reward_risk_ratio": round(net_rr, 2),
            "minimum_net_reward_cost_multiple": (
                self.config.minimum_net_reward_cost_multiple
            ),
            "minimum_net_reward_risk_ratio": (
                self.config.minimum_net_reward_risk_ratio
            ),
            "candidate_context_supplied": bool(candidate_context),
        }
        metrics = {
            "estimated_round_trip_cost": estimated_cost,
            "expected_gross_reward": gross_reward,
            "expected_net_reward": net_reward,
            "net_reward_cost_multiple": cost_multiple,
            "net_reward_risk_ratio": net_rr,
        }

        reasons: list[str] = []
        if net_reward <= 0:
            reasons.append("Expected target-1 reward is negative after costs")
        if cost_multiple < self.config.minimum_net_reward_cost_multiple:
            reasons.append("Net reward is too small relative to estimated costs")
        if net_rr < self.config.minimum_net_reward_risk_ratio:
            reasons.append("Net reward/risk ratio is below the configured minimum")
        if reasons:
            return (
                GateCheck(
                    "NET_COST_EXPECTANCY",
                    GateStatus.BLOCK,
                    "; ".join(reasons),
                    details,
                ),
                metrics,
            )
        return (
            GateCheck(
                "NET_COST_EXPECTANCY",
                GateStatus.PASS,
                "Expected target-1 reward remains positive after estimated costs",
                details,
            ),
            metrics,
        )

    def _unknown_or_block(
        self,
        name: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> GateCheck:
        return GateCheck(
            name,
            GateStatus.BLOCK if self.config.strict else GateStatus.UNKNOWN,
            message,
            dict(details or {}),
        )

    def _load_holidays(self) -> set[date]:
        rows = _read_csv(self.safety_dir / "nse_holidays.csv")
        result: set[date] = set()
        for row in rows:
            value = _parse_date(row.get("date"))
            if value is not None:
                result.add(value)
        return result

    # APLUS_PAPER_CIRCUIT_BREAKER_WIRING_V1
    def _load_portfolio_state(self) -> dict[str, Any]:
        primary = self.data_dir / "portfolio_state.json"
        legacy = self.safety_dir / "portfolio_state.json"
        path = primary if primary.exists() else legacy
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        result = dict(payload) if isinstance(payload, Mapping) else {}
        result.setdefault("_portfolio_state_path", str(path))
        return result


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, "").strip()
    value = default if not raw else int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name, "").strip()
    value = default if not raw else float(raw)
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return value


def _value(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _first_number(
    mapping: Mapping[str, Any],
    names: Iterable[str],
    *,
    default: float,
) -> float:
    for name in names:
        if name in mapping:
            return _number(mapping.get(name), default)
    return default


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text[:10]):
        for fmt in (
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y/%m/%d",
        ):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def _as_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)


def _trading_days_between(
    start: date,
    end: date,
    *,
    holidays: set[date],
) -> int:
    if end <= start:
        return 0
    cursor = start + timedelta(days=1)
    count = 0
    while cursor <= end:
        if cursor.weekday() < 5 and cursor not in holidays:
            count += 1
        cursor += timedelta(days=1)
    return count


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, csv.Error):
        return []


__all__ = [
    "GateCheck",
    "GateStatus",
    "SafetyGateConfig",
    "SafetyGateEngine",
    "SafetyGateResult",
]
