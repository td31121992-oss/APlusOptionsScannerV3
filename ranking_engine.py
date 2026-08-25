"""
ranking_engine.py

Ranks strategy signals by confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from analytics.models import RankedStock, StrategySignal


@dataclass(slots=True)
class RankingConfig:
    minimum_score: float = 50.0
    top_n: int = 20


class RankingEngine:
    def __init__(self, config: RankingConfig | None = None) -> None:
        self.config = config or RankingConfig()

    def rank(self, signals: list[StrategySignal]) -> list[RankedStock]:
        eligible = [
            s for s in signals
            if s.confidence >= self.config.minimum_score
        ]

        eligible.sort(
            key=lambda x: (x.confidence, x.strength),
            reverse=True,
        )

        ranked: list[RankedStock] = []

        for index, signal in enumerate(
            eligible[: self.config.top_n],
            start=1,
        ):
            ranked.append(
                RankedStock(
                    rank=index,
                    symbol=signal.symbol,
                    score=signal.confidence,
                    signal=signal,
                )
            )

        return ranked
