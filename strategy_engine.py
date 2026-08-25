"""
strategy_engine.py

Combines analytics into a trading signal.
"""

from __future__ import annotations

from dataclasses import dataclass

from analytics.confidence_engine import ConfidenceAnalysis
from analytics.enums import MarketBias, RecommendationType
from analytics.models import StrategySignal


@dataclass(slots=True)
class StrategyConfig:
    bullish_threshold: float = 70.0
    bearish_threshold: float = 70.0


class StrategyEngine:
    def __init__(
        self,
        config: StrategyConfig | None = None,
    ) -> None:
        self.config = config or StrategyConfig()

    def analyze(
        self,
        symbol: str,
        confidence: ConfidenceAnalysis,
    ) -> StrategySignal:
        bias = confidence.bias
        strength = confidence.score

        if (
            bias == MarketBias.BULLISH
            and strength >= self.config.bullish_threshold
        ):
            recommendation = RecommendationType.BUY

        elif (
            bias == MarketBias.BEARISH
            and strength >= self.config.bearish_threshold
        ):
            recommendation = RecommendationType.SELL

        else:
            recommendation = RecommendationType.HOLD

        return StrategySignal(
            symbol=symbol,
            bias=bias,
            strength=strength,
            confidence=confidence.score,
            recommendation=recommendation,
            reasons=list(confidence.reasons),
        )


__all__ = [
    "StrategyConfig",
    "StrategyEngine",
]
