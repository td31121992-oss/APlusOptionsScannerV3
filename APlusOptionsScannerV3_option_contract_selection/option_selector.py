"""
option_selector.py

Select one executable long-option contract for an actionable underlying signal.
Bullish signals buy a Call (CE); bearish signals buy a Put (PE). The selector
uses the already-fetched option chain and exact instrument-master metadata, so
it adds no Dhan API request.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any, Mapping, Sequence

from analytics.enums import MarketBias, OptionSide, RecommendationType
from analytics.models import (
    OptionChainSnapshot,
    OptionContractSelection,
    OptionLeg,
)


class OptionSelectionError(RuntimeError):
    """Raised when no safe executable option contract can be selected."""


@dataclass(frozen=True, slots=True)
class OptionSelectionConfig:
    minimum_ltp: float = 2.0
    maximum_ltp: float = 250.0
    minimum_oi: int = 5_000
    minimum_volume: int = 500
    maximum_spread_percent: float = 5.0
    maximum_moneyness_percent: float = 3.0
    target_itm_percent: float = 0.50

    limit_buffer_percent: float = 0.50
    option_stop_loss_percent: float = 25.0
    target1_reward_risk: float = 1.0
    target2_reward_risk: float = 1.75
    target3_reward_risk: float = 2.5

    maximum_premium_per_trade: float = 100_000.0
    maximum_risk_per_trade: float = 25_000.0
    maximum_lots: int = 1

    @classmethod
    def from_env(cls) -> "OptionSelectionConfig":
        defaults = cls()
        return cls(
            minimum_ltp=cls._env_float(
                "APLUS_OPTION_MIN_LTP", defaults.minimum_ltp
            ),
            maximum_ltp=cls._env_float(
                "APLUS_OPTION_MAX_LTP", defaults.maximum_ltp
            ),
            minimum_oi=cls._env_int(
                "APLUS_OPTION_MIN_OI", defaults.minimum_oi
            ),
            minimum_volume=cls._env_int(
                "APLUS_OPTION_MIN_VOLUME", defaults.minimum_volume
            ),
            maximum_spread_percent=cls._env_float(
                "APLUS_OPTION_MAX_SPREAD_PERCENT",
                defaults.maximum_spread_percent,
            ),
            maximum_moneyness_percent=cls._env_float(
                "APLUS_OPTION_MAX_MONEYNESS_PERCENT",
                defaults.maximum_moneyness_percent,
            ),
            target_itm_percent=cls._env_float(
                "APLUS_OPTION_TARGET_ITM_PERCENT",
                defaults.target_itm_percent,
            ),
            limit_buffer_percent=cls._env_float(
                "APLUS_OPTION_LIMIT_BUFFER_PERCENT",
                defaults.limit_buffer_percent,
            ),
            option_stop_loss_percent=cls._env_float(
                "APLUS_OPTION_STOP_LOSS_PERCENT",
                defaults.option_stop_loss_percent,
            ),
            target1_reward_risk=cls._env_float(
                "APLUS_OPTION_TARGET1_RR",
                defaults.target1_reward_risk,
            ),
            target2_reward_risk=cls._env_float(
                "APLUS_OPTION_TARGET2_RR",
                defaults.target2_reward_risk,
            ),
            target3_reward_risk=cls._env_float(
                "APLUS_OPTION_TARGET3_RR",
                defaults.target3_reward_risk,
            ),
            maximum_premium_per_trade=cls._env_float(
                "APLUS_OPTION_MAX_PREMIUM_PER_TRADE",
                defaults.maximum_premium_per_trade,
            ),
            maximum_risk_per_trade=cls._env_float(
                "APLUS_OPTION_MAX_RISK_PER_TRADE",
                defaults.maximum_risk_per_trade,
            ),
            maximum_lots=cls._env_int(
                "APLUS_OPTION_MAX_LOTS", defaults.maximum_lots
            ),
        )

    def __post_init__(self) -> None:
        if not 0 < self.minimum_ltp < self.maximum_ltp:
            raise ValueError(
                "Expected 0 < minimum_ltp < maximum_ltp"
            )
        if self.minimum_oi < 0 or self.minimum_volume < 0:
            raise ValueError("OI and volume thresholds cannot be negative")
        for name, value in (
            ("maximum_spread_percent", self.maximum_spread_percent),
            ("maximum_moneyness_percent", self.maximum_moneyness_percent),
            ("limit_buffer_percent", self.limit_buffer_percent),
            ("option_stop_loss_percent", self.option_stop_loss_percent),
            ("maximum_premium_per_trade", self.maximum_premium_per_trade),
            ("maximum_risk_per_trade", self.maximum_risk_per_trade),
        ):
            if not isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not 0 < self.option_stop_loss_percent < 100:
            raise ValueError(
                "option_stop_loss_percent must be between 0 and 100"
            )
        if not (
            0 < self.target1_reward_risk
            < self.target2_reward_risk
            < self.target3_reward_risk
        ):
            raise ValueError("Reward/risk targets must increase")
        if self.maximum_lots < 1:
            raise ValueError("maximum_lots must be at least 1")

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return float(default)
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be numeric") from exc

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            return int(default)
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc


@dataclass(slots=True)
class _Candidate:
    leg: OptionLeg
    contract: Any
    option_type: str
    entry: float
    spread_percent: float
    moneyness_percent: float
    target_distance_percent: float
    score: float


class OptionSelector:
    """Choose the most executable ATM/slightly-ITM long option."""

    def __init__(
        self,
        config: OptionSelectionConfig | None = None,
    ) -> None:
        self.config = config or OptionSelectionConfig.from_env()

    def select(
        self,
        *,
        snapshot: OptionChainSnapshot,
        underlying: Any,
        recommendation: RecommendationType,
        bias: MarketBias,
    ) -> OptionContractSelection:
        spot = self._positive_float(snapshot.underlying_ltp)
        if spot is None:
            raise OptionSelectionError("Underlying LTP is unavailable")

        option_side, option_type = self._required_side(
            recommendation,
            bias,
        )

        contracts = list(getattr(underlying, "contracts", []) or [])
        if not contracts:
            raise OptionSelectionError(
                "Instrument-master option contracts are unavailable"
            )

        by_security_id, by_key = self._contract_indexes(contracts)
        candidates: list[_Candidate] = []
        rejection_counts: dict[str, int] = {}

        for strike_data in snapshot.strikes:
            leg = (
                strike_data.call
                if option_side == OptionSide.CALL
                else strike_data.put
            )
            if leg is None:
                continue

            contract = by_security_id.get(
                self._normalize_id(leg.security_id)
            )
            if contract is None:
                contract = by_key.get(
                    self._contract_key(
                        snapshot.expiry,
                        leg.strike,
                        option_type,
                    )
                )
            if contract is None:
                self._reject(rejection_counts, "NO_CONTRACT_METADATA")
                continue

            candidate, reason = self._candidate(
                leg=leg,
                contract=contract,
                option_type=option_type,
                spot=spot,
            )
            if candidate is None:
                self._reject(rejection_counts, reason)
                continue
            candidates.append(candidate)

        if not candidates:
            details = ", ".join(
                f"{key}={value}"
                for key, value in sorted(rejection_counts.items())
            ) or "no matching CE/PE legs"
            raise OptionSelectionError(
                f"No executable {option_type} contract for "
                f"{snapshot.symbol} {snapshot.expiry}: {details}"
            )

        selected = max(
            candidates,
            key=lambda item: (
                item.score,
                -item.target_distance_percent,
                -item.spread_percent,
                item.leg.oi,
                item.leg.volume,
            ),
        )

        return self._build_selection(
            snapshot=snapshot,
            selected=selected,
        )

    def _candidate(
        self,
        *,
        leg: OptionLeg,
        contract: Any,
        option_type: str,
        spot: float,
    ) -> tuple[_Candidate | None, str]:
        cfg = self.config

        ltp = self._positive_float(leg.ltp)
        bid = self._positive_float(leg.bid)
        ask = self._positive_float(leg.ask)

        if ltp is None or not cfg.minimum_ltp <= ltp <= cfg.maximum_ltp:
            return None, "PREMIUM_OUTSIDE_RANGE"
        if bid is None or ask is None or ask < bid:
            return None, "NO_EXECUTABLE_DEPTH"

        spread_percent = ((ask - bid) / ask) * 100.0
        if spread_percent > cfg.maximum_spread_percent:
            return None, "WIDE_SPREAD"
        if int(leg.oi or 0) < cfg.minimum_oi:
            return None, "LOW_OI"
        if int(leg.volume or 0) < cfg.minimum_volume:
            return None, "LOW_VOLUME"

        lot_size = self._positive_int(getattr(contract, "lot_size", 0))
        tick_size = self._positive_float(getattr(contract, "tick_size", 0))
        if lot_size is None:
            return None, "MISSING_LOT_SIZE"
        if tick_size is None:
            return None, "MISSING_TICK_SIZE"

        strike = self._positive_float(leg.strike)
        if strike is None:
            return None, "INVALID_STRIKE"

        moneyness_percent = abs(strike - spot) / spot * 100.0
        if moneyness_percent > cfg.maximum_moneyness_percent:
            return None, "TOO_FAR_FROM_SPOT"

        target = (
            spot * (1.0 - cfg.target_itm_percent / 100.0)
            if option_type == "CE"
            else spot * (1.0 + cfg.target_itm_percent / 100.0)
        )
        target_distance_percent = abs(strike - target) / spot * 100.0

        entry = self._round_up(
            ask * (1.0 + cfg.limit_buffer_percent / 100.0),
            tick_size,
        )
        if entry > cfg.maximum_ltp:
            return None, "BUFFERED_PRICE_TOO_HIGH"

        premium_per_lot = entry * lot_size
        risk_per_unit = entry * cfg.option_stop_loss_percent / 100.0
        risk_per_lot = risk_per_unit * lot_size

        affordable_lots = int(
            cfg.maximum_premium_per_trade // premium_per_lot
        )
        risk_lots = int(
            cfg.maximum_risk_per_trade // risk_per_lot
        )
        lots = min(cfg.maximum_lots, affordable_lots, risk_lots)
        if lots < 1:
            return None, "ONE_LOT_EXCEEDS_RISK_OR_PREMIUM_LIMIT"

        moneyness_score = self._score_inverse(
            target_distance_percent,
            cfg.maximum_moneyness_percent,
        )
        spread_score = self._score_inverse(
            spread_percent,
            cfg.maximum_spread_percent,
        )
        oi_score = min(100.0, (leg.oi / max(1, cfg.minimum_oi)) * 40.0)
        volume_score = min(
            100.0,
            (leg.volume / max(1, cfg.minimum_volume)) * 40.0,
        )

        score = (
            moneyness_score * 0.35
            + spread_score * 0.30
            + oi_score * 0.20
            + volume_score * 0.15
        )

        return (
            _Candidate(
                leg=leg,
                contract=contract,
                option_type=option_type,
                entry=entry,
                spread_percent=spread_percent,
                moneyness_percent=moneyness_percent,
                target_distance_percent=target_distance_percent,
                score=score,
            ),
            "",
        )

    def _build_selection(
        self,
        *,
        snapshot: OptionChainSnapshot,
        selected: _Candidate,
    ) -> OptionContractSelection:
        cfg = self.config
        contract = selected.contract
        leg = selected.leg

        lot_size = int(getattr(contract, "lot_size"))
        tick_size = float(getattr(contract, "tick_size"))

        premium_per_lot = selected.entry * lot_size
        risk_per_unit = selected.entry * cfg.option_stop_loss_percent / 100.0
        risk_per_lot = risk_per_unit * lot_size

        affordable_lots = int(
            cfg.maximum_premium_per_trade // premium_per_lot
        )
        risk_lots = int(
            cfg.maximum_risk_per_trade // risk_per_lot
        )
        lots = min(cfg.maximum_lots, affordable_lots, risk_lots)
        quantity = lot_size * lots

        stop_loss = self._round_down(
            selected.entry - risk_per_unit,
            tick_size,
        )
        target1 = self._round_up(
            selected.entry
            + risk_per_unit * cfg.target1_reward_risk,
            tick_size,
        )
        target2 = self._round_up(
            selected.entry
            + risk_per_unit * cfg.target2_reward_risk,
            tick_size,
        )
        target3 = self._round_up(
            selected.entry
            + risk_per_unit * cfg.target3_reward_risk,
            tick_size,
        )

        security_id = self._normalize_id(leg.security_id)
        if not security_id:
            security_id = self._normalize_id(
                getattr(contract, "derivative_security_id", "")
            )

        reason = (
            f"Selected {selected.option_type} strike {leg.strike:.2f}; "
            f"distance from spot {selected.moneyness_percent:.2f}%; "
            f"spread {selected.spread_percent:.2f}%; "
            f"OI {int(leg.oi)}; volume {int(leg.volume)}; "
            f"{lots} lot(s)"
        )

        return OptionContractSelection(
            exchange_segment=str(
                getattr(contract, "exchange_segment", "NSE_FNO")
            ),
            security_id=security_id,
            trading_symbol=str(
                getattr(contract, "trading_symbol", "") or ""
            ),
            display_name=str(
                getattr(contract, "display_name", "") or ""
            ),
            expiry=self._normalize_expiry(snapshot.expiry),
            option_type=selected.option_type,
            transaction="BUY",
            strike=round(float(leg.strike), 4),
            ltp=round(float(leg.ltp), 2),
            bid=round(float(leg.bid), 2),
            ask=round(float(leg.ask), 2),
            limit_price=round(selected.entry, 2),
            tick_size=round(tick_size, 4),
            oi=int(leg.oi),
            volume=int(leg.volume),
            iv=round(float(leg.iv or 0.0), 4),
            spread_percent=round(selected.spread_percent, 2),
            lot_size=lot_size,
            lots=lots,
            quantity=quantity,
            premium_per_lot=round(premium_per_lot, 2),
            total_premium=round(selected.entry * quantity, 2),
            stop_loss=round(stop_loss, 2),
            target1=round(target1, 2),
            target2=round(target2, 2),
            target3=round(target3, 2),
            risk_per_unit=round(risk_per_unit, 2),
            risk_per_lot=round(risk_per_lot, 2),
            total_risk=round(risk_per_unit * quantity, 2),
            selection_score=round(selected.score, 2),
            selection_reason=reason,
        )

    @staticmethod
    def _required_side(
        recommendation: RecommendationType,
        bias: MarketBias,
    ) -> tuple[OptionSide, str]:
        if (
            recommendation == RecommendationType.BUY
            and bias == MarketBias.BULLISH
        ):
            return OptionSide.CALL, "CE"
        if (
            recommendation == RecommendationType.SELL
            and bias == MarketBias.BEARISH
        ):
            return OptionSide.PUT, "PE"
        raise OptionSelectionError(
            "Signal recommendation and market bias are not actionable"
        )

    def _contract_indexes(
        self,
        contracts: Sequence[Any],
    ) -> tuple[dict[str, Any], dict[tuple[str, str, str], Any]]:
        by_security_id: dict[str, Any] = {}
        by_key: dict[tuple[str, str, str], Any] = {}

        for contract in contracts:
            security_id = self._normalize_id(
                self._value(contract, "derivative_security_id")
            )
            expiry = self._normalize_expiry(
                self._value(contract, "expiry")
            )
            strike = self._positive_float(
                self._value(contract, "strike")
            )
            option_type = self._normalize_option_type(
                self._value(contract, "option_type")
            )

            if security_id:
                by_security_id[security_id] = contract
            if expiry and strike is not None and option_type:
                by_key[self._contract_key(
                    expiry,
                    strike,
                    option_type,
                )] = contract

        return by_security_id, by_key

    @staticmethod
    def _value(item: Any, name: str) -> Any:
        if isinstance(item, Mapping):
            return item.get(name)
        return getattr(item, name, None)

    @staticmethod
    def _contract_key(
        expiry: Any,
        strike: Any,
        option_type: Any,
    ) -> tuple[str, str, str]:
        normalized_strike = OptionSelector._positive_float(strike)
        strike_key = (
            f"{normalized_strike:.8f}".rstrip("0").rstrip(".")
            if normalized_strike is not None
            else ""
        )
        return (
            OptionSelector._normalize_expiry(expiry),
            strike_key,
            OptionSelector._normalize_option_type(option_type),
        )

    @staticmethod
    def _normalize_expiry(value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()

        text = str(value or "").strip()
        if not text:
            return ""
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return ""

    @staticmethod
    def _normalize_option_type(value: Any) -> str:
        text = str(value or "").strip().upper()
        if text in {"CE", "CALL", "C", "OPTIONSIDE.CALL"}:
            return "CE"
        if text in {"PE", "PUT", "P", "OPTIONSIDE.PUT"}:
            return "PE"
        return ""

    @staticmethod
    def _normalize_id(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            number = float(text)
        except (TypeError, ValueError):
            return text
        return str(int(number)) if number.is_integer() else text

    @staticmethod
    def _positive_float(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not isfinite(number) or number <= 0:
            return None
        return number

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            number = int(float(value))
        except (TypeError, ValueError, OverflowError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _score_inverse(value: float, maximum: float) -> float:
        if maximum <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (1.0 - value / maximum)))

    @staticmethod
    def _round_up(value: float, tick: float) -> float:
        return math.ceil((value - 1e-12) / tick) * tick

    @staticmethod
    def _round_down(value: float, tick: float) -> float:
        return max(tick, math.floor((value + 1e-12) / tick) * tick)

    @staticmethod
    def _reject(counts: dict[str, int], reason: str) -> None:
        counts[reason] = counts.get(reason, 0) + 1


__all__ = [
    "OptionSelectionConfig",
    "OptionSelectionError",
    "OptionSelector",
]
