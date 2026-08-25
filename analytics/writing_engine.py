"""
analytics/writing_engine.py

Detects Call/Put writing from option-chain changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import SignalType, WritingType
from .models import OptionChainSnapshot, OptionLeg


@dataclass(slots=True)
class WritingSignal:
    signal: SignalType
    writing_type: WritingType
    score: float
    reason: str


@dataclass(slots=True)
class WritingThresholds:
    min_oi_change: int = 100
    max_price_change_percent: float = -0.25


class WritingEngine:
    def __init__(self, thresholds: WritingThresholds | None = None) -> None:
        self.thresholds = thresholds or WritingThresholds()

    def analyze_leg(self, leg: OptionLeg) -> WritingSignal:
        oi_up = leg.oi_change >= self.thresholds.min_oi_change
        premium_down = (
            leg.price_change_percent <= self.thresholds.max_price_change_percent
        )

        if not (oi_up and premium_down):
            return WritingSignal(
                signal=SignalType.NEUTRAL,
                writing_type=WritingType.NONE,
                score=0.0,
                reason="No writing detected",
            )

        if leg.side.value == "CALL":
            return WritingSignal(
                signal=SignalType.CALL_WRITING,
                writing_type=WritingType.CALL_WRITING,
                score=85.0,
                reason="OI increased while Call premium fell",
            )

        return WritingSignal(
            signal=SignalType.PUT_WRITING,
            writing_type=WritingType.PUT_WRITING,
            score=85.0,
            reason="OI increased while Put premium fell",
        )

    def analyze_snapshot(
        self,
        snapshot: OptionChainSnapshot,
    ) -> dict[str, list[WritingSignal]]:
        calls: list[WritingSignal] = []
        puts: list[WritingSignal] = []

        for strike in snapshot.strikes:
            if strike.call:
                calls.append(self.analyze_leg(strike.call))
            if strike.put:
                puts.append(self.analyze_leg(strike.put))

        return {
            "calls": calls,
            "puts": puts,
        }
