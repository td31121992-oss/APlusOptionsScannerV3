"""
analytics/liquidity_engine.py

Liquidity scoring engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import LiquidityGrade
from .models import LiquidityAnalysis, OptionChainSnapshot


@dataclass(slots=True)
class LiquidityThresholds:
    excellent_spread: float = 0.20
    good_spread: float = 0.50
    average_spread: float = 1.00
    min_volume: int = 100


class LiquidityEngine:
    def __init__(
        self,
        thresholds: LiquidityThresholds | None = None,
    ) -> None:
        self.thresholds = thresholds or LiquidityThresholds()

    def analyze(
        self,
        snapshot: OptionChainSnapshot,
    ) -> LiquidityAnalysis:
        spreads: list[float] = []
        total_volume = 0
        contracts = 0

        for strike in snapshot.strikes:
            for leg in (strike.call, strike.put):
                if leg is None:
                    continue

                contracts += 1
                total_volume += max(0, int(leg.volume))

                if leg.ask > 0 and leg.bid > 0:
                    spreads.append(
                        max(0.0, float(leg.ask) - float(leg.bid))
                    )

        average_spread = (
            sum(spreads) / len(spreads)
            if spreads
            else 999.0
        )
        average_volume = (
            total_volume / contracts
            if contracts
            else 0.0
        )

        if (
            average_spread <= self.thresholds.excellent_spread
            and average_volume >= 5 * self.thresholds.min_volume
        ):
            score = 100.0
            grade = LiquidityGrade.EXCELLENT

        elif (
            average_spread <= self.thresholds.good_spread
            and average_volume >= 3 * self.thresholds.min_volume
        ):
            score = 80.0
            grade = LiquidityGrade.GOOD

        elif (
            average_spread <= self.thresholds.average_spread
            and average_volume >= self.thresholds.min_volume
        ):
            score = 60.0
            grade = LiquidityGrade.AVERAGE

        elif average_volume > 0:
            score = 40.0
            grade = LiquidityGrade.LOW

        else:
            score = 10.0
            grade = LiquidityGrade.POOR

        return LiquidityAnalysis(
            score=score,
            average_spread=round(average_spread, 4),
            grade=grade,
            average_volume=round(average_volume, 2),
        )


__all__ = [
    "LiquidityEngine",
    "LiquidityThresholds",
]
