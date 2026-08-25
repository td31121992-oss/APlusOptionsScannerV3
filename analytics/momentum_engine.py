"""
analytics/momentum_engine.py

Underlying and option premium momentum analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import MomentumStrength, PriceDirection
from .models import OptionChainSnapshot


@dataclass(slots=True)
class MomentumAnalysis:
    direction: PriceDirection
    strength: MomentumStrength
    underlying_change_percent: float
    average_option_change_percent: float
    score: float


@dataclass(slots=True)
class MomentumThresholds:
    strong: float = 2.0
    moderate: float = 0.75


class MomentumEngine:
    def __init__(self, thresholds: MomentumThresholds | None = None) -> None:
        self.thresholds = thresholds or MomentumThresholds()

    def analyze(
        self,
        snapshot: OptionChainSnapshot,
        previous_underlying_ltp: float | None = None,
    ) -> MomentumAnalysis:

        underlying_change = 0.0
        if previous_underlying_ltp and previous_underlying_ltp > 0:
            underlying_change = (
                (snapshot.underlying_ltp - previous_underlying_ltp)
                / previous_underlying_ltp
            ) * 100.0

        changes = [
            leg.price_change_percent
            for leg in snapshot.all_legs()
        ]
        avg_option_change = (
            sum(changes) / len(changes)
            if changes else 0.0
        )

        value = underlying_change if underlying_change != 0 else avg_option_change

        if value >= self.thresholds.strong:
            direction = PriceDirection.UP
            strength = MomentumStrength.STRONG
            score = 100.0
        elif value >= self.thresholds.moderate:
            direction = PriceDirection.UP
            strength = MomentumStrength.MODERATE
            score = 75.0
        elif value <= -self.thresholds.strong:
            direction = PriceDirection.DOWN
            strength = MomentumStrength.STRONG
            score = 100.0
        elif value <= -self.thresholds.moderate:
            direction = PriceDirection.DOWN
            strength = MomentumStrength.MODERATE
            score = 75.0
        else:
            direction = PriceDirection.FLAT
            strength = MomentumStrength.WEAK
            score = 25.0

        return MomentumAnalysis(
            direction=direction,
            strength=strength,
            underlying_change_percent=round(underlying_change, 2),
            average_option_change_percent=round(avg_option_change, 2),
            score=score,
        )
