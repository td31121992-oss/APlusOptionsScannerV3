"""
trade_engine.py

Generate conservative recommendations containing an exact executable long-option
contract. HOLD/NEUTRAL signals and signals without a safe contract are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from analytics.enums import MarketBias, RecommendationType
from analytics.models import (
    OptionChainSnapshot,
    RankedStock,
    TradeRecommendation,
)
from logger import get_logger
from option_selector import (
    OptionSelectionError,
    OptionSelector,
)


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TradeConfig:
    stop_loss_percent: float = 1.0
    target1_percent: float = 1.5
    target2_percent: float = 3.0
    target3_percent: float = 5.0
    minimum_confidence: float = 75.0
    maximum_recommendations: int = 10

    def __post_init__(self) -> None:
        percentages = (
            self.stop_loss_percent,
            self.target1_percent,
            self.target2_percent,
            self.target3_percent,
        )
        if any(
            not isfinite(float(value)) or float(value) <= 0
            for value in percentages
        ):
            raise ValueError(
                "Stop-loss and target percentages must be positive"
            )
        if not (
            self.target1_percent
            < self.target2_percent
            < self.target3_percent
        ):
            raise ValueError(
                "Targets must satisfy target1 < target2 < target3"
            )
        if not 0 <= self.minimum_confidence <= 100:
            raise ValueError(
                "minimum_confidence must be between 0 and 100"
            )
        if self.maximum_recommendations < 1:
            raise ValueError(
                "maximum_recommendations must be at least 1"
            )


class TradeEngine:
    """Convert actionable signals into executable option-buy plans."""

    def __init__(
        self,
        config: TradeConfig | None = None,
        *,
        option_selector: OptionSelector | None = None,
    ) -> None:
        self.config = config or TradeConfig()
        self.option_selector = option_selector or OptionSelector()

    def generate(
        self,
        ranked: list[RankedStock],
        prices: dict[str, float],
        *,
        snapshots: Mapping[str, OptionChainSnapshot] | None = None,
        underlyings: Mapping[str, Any] | None = None,
    ) -> list[TradeRecommendation]:
        if snapshots is None or underlyings is None:
            logger.warning(
                "Executable option selection skipped: snapshots or "
                "instrument metadata were not supplied"
            )
            return []

        trades: list[TradeRecommendation] = []
        seen_symbols: set[str] = set()
        normalized_prices = self._normalize_prices(prices)
        normalized_snapshots = {
            self._normalize_symbol(symbol): snapshot
            for symbol, snapshot in snapshots.items()
        }
        normalized_underlyings = {
            self._normalize_symbol(symbol): underlying
            for symbol, underlying in underlyings.items()
        }

        for stock in ranked:
            if len(trades) >= self.config.maximum_recommendations:
                break

            symbol = self._normalize_symbol(stock.symbol)
            if not symbol or symbol in seen_symbols:
                continue

            signal = getattr(stock, "signal", None)
            if signal is None:
                continue

            recommendation = self._recommendation(
                getattr(
                    signal,
                    "recommendation",
                    RecommendationType.HOLD,
                )
            )
            if recommendation == RecommendationType.HOLD:
                continue

            bias = self._bias(
                getattr(signal, "bias", MarketBias.NEUTRAL)
            )
            if not self._direction_is_consistent(
                recommendation,
                bias,
            ):
                continue

            confidence = self._finite_float(
                getattr(signal, "confidence", 0.0)
            )
            if (
                confidence is None
                or confidence < self.config.minimum_confidence
            ):
                continue

            entry = normalized_prices.get(symbol)
            snapshot = normalized_snapshots.get(symbol)
            underlying = normalized_underlyings.get(symbol)
            if entry is None or snapshot is None or underlying is None:
                logger.info(
                    "Skipping %s: missing price, snapshot or instrument metadata",
                    symbol,
                )
                continue

            levels = self._calculate_underlying_levels(
                entry,
                recommendation,
            )
            if levels is None:
                continue

            try:
                option_contract = self.option_selector.select(
                    snapshot=snapshot,
                    underlying=underlying,
                    recommendation=recommendation,
                    bias=bias,
                )
            except OptionSelectionError as exc:
                logger.info(
                    "Skipping option recommendation for %s: %s",
                    symbol,
                    exc,
                )
                continue

            stop_loss, target1, target2, target3 = levels
            trades.append(
                TradeRecommendation(
                    symbol=symbol,
                    recommendation=recommendation,
                    entry=round(entry, 2),
                    stop_loss=round(stop_loss, 2),
                    target1=round(target1, 2),
                    target2=round(target2, 2),
                    target3=round(target3, 2),
                    confidence=round(confidence, 2),
                    option_contract=option_contract,
                )
            )
            seen_symbols.add(symbol)

        return trades

    def _calculate_underlying_levels(
        self,
        entry: float,
        recommendation: RecommendationType,
    ) -> tuple[float, float, float, float] | None:
        cfg = self.config
        stop_fraction = cfg.stop_loss_percent / 100.0
        target1_fraction = cfg.target1_percent / 100.0
        target2_fraction = cfg.target2_percent / 100.0
        target3_fraction = cfg.target3_percent / 100.0

        if recommendation == RecommendationType.BUY:
            levels = (
                entry * (1.0 - stop_fraction),
                entry * (1.0 + target1_fraction),
                entry * (1.0 + target2_fraction),
                entry * (1.0 + target3_fraction),
            )
        elif recommendation == RecommendationType.SELL:
            levels = (
                entry * (1.0 + stop_fraction),
                entry * (1.0 - target1_fraction),
                entry * (1.0 - target2_fraction),
                entry * (1.0 - target3_fraction),
            )
        else:
            return None

        if any(
            not isfinite(level) or level <= 0
            for level in levels
        ):
            return None
        return levels

    @staticmethod
    def _direction_is_consistent(
        recommendation: RecommendationType,
        bias: MarketBias,
    ) -> bool:
        return (
            recommendation == RecommendationType.BUY
            and bias == MarketBias.BULLISH
        ) or (
            recommendation == RecommendationType.SELL
            and bias == MarketBias.BEARISH
        )

    @classmethod
    def _normalize_prices(
        cls,
        prices: Mapping[str, float],
    ) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for raw_symbol, raw_price in prices.items():
            symbol = cls._normalize_symbol(raw_symbol)
            price = cls._finite_float(raw_price)
            if symbol and price is not None and price > 0:
                normalized[symbol] = price
        return normalized

    @staticmethod
    def _normalize_symbol(value: Any) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _finite_float(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if isfinite(number) else None

    @staticmethod
    def _bias(value: Any) -> MarketBias:
        if isinstance(value, MarketBias):
            return value
        text = str(value or "").strip().upper().rsplit(".", 1)[-1]
        if text == "BULLISH":
            return MarketBias.BULLISH
        if text == "BEARISH":
            return MarketBias.BEARISH
        return MarketBias.NEUTRAL

    @staticmethod
    def _recommendation(value: Any) -> RecommendationType:
        if isinstance(value, RecommendationType):
            return value
        text = str(value or "").strip().upper().rsplit(".", 1)[-1]
        if text == "BUY":
            return RecommendationType.BUY
        if text == "SELL":
            return RecommendationType.SELL
        return RecommendationType.HOLD


__all__ = ["TradeConfig", "TradeEngine"]
