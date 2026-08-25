"""
analytics/max_pain_engine.py

Max Pain analysis for one normalized option-chain snapshot.

Interpretation
--------------
Max Pain is treated as a low-weight price-magnet estimate:

* Max Pain above spot  -> bullish/upward pull
* Max Pain below spot  -> bearish/downward pull
* Max Pain near spot   -> neutral

``distance_from_spot`` is stored as ``max_pain - spot``. Therefore a positive
distance means Max Pain is above spot, and a negative distance means it is
below spot.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from analytics.enums import MarketBias
from analytics.models import (
    MaxPainAnalysis,
    OptionChainSnapshot,
)


@dataclass(frozen=True, slots=True)
class MaxPainConfig:
    """Configuration for Max Pain calculation and directional tolerance."""

    minimum_oi: int = 100

    # Max Pain within the larger of these two thresholds is treated as neutral.
    minimum_neutral_distance: float = 0.50
    neutral_distance_percent: float = 0.25

    def __post_init__(self) -> None:
        if self.minimum_oi < 0:
            raise ValueError("minimum_oi cannot be negative")

        if (
            not isfinite(float(self.minimum_neutral_distance))
            or self.minimum_neutral_distance < 0
        ):
            raise ValueError(
                "minimum_neutral_distance must be a "
                "non-negative finite number"
            )

        if (
            not isfinite(float(self.neutral_distance_percent))
            or self.neutral_distance_percent < 0
        ):
            raise ValueError(
                "neutral_distance_percent must be a "
                "non-negative finite number"
            )


class MaxPainEngine:
    """Calculate Max Pain and its low-weight directional context."""

    def __init__(
        self,
        config: MaxPainConfig | None = None,
    ) -> None:
        self.config = config or MaxPainConfig()

    def analyze(
        self,
        snapshot: OptionChainSnapshot,
    ) -> MaxPainAnalysis:
        strikes = self._valid_strikes(snapshot)

        if not strikes:
            return MaxPainAnalysis()

        total_pain: dict[float, float] = {}

        # Candidate settlement prices are the unique available strikes.
        settlement_prices = sorted(
            {float(strike.strike) for strike in strikes}
        )

        for settlement_price in settlement_prices:
            call_pain = 0.0
            put_pain = 0.0

            for strike_data in strikes:
                strike_price = float(strike_data.strike)

                call = strike_data.call
                if call is not None:
                    call_oi = self._valid_oi(
                        getattr(call, "oi", 0)
                    )
                    if call_oi >= self.config.minimum_oi:
                        # Call writer payout/loss at settlement.
                        call_intrinsic = max(
                            0.0,
                            settlement_price - strike_price,
                        )
                        call_pain += call_intrinsic * call_oi

                put = strike_data.put
                if put is not None:
                    put_oi = self._valid_oi(
                        getattr(put, "oi", 0)
                    )
                    if put_oi >= self.config.minimum_oi:
                        # Put writer payout/loss at settlement.
                        put_intrinsic = max(
                            0.0,
                            strike_price - settlement_price,
                        )
                        put_pain += put_intrinsic * put_oi

            total_pain[settlement_price] = call_pain + put_pain

        if not total_pain:
            return MaxPainAnalysis()

        # Deterministic tie-break: choose the candidate closest to spot, then
        # the lower strike. This prevents arbitrary results when pain ties.
        spot = self._valid_spot(
            getattr(snapshot, "underlying_ltp", 0.0)
        )

        max_pain_strike = min(
            total_pain,
            key=lambda strike: (
                total_pain[strike],
                abs(strike - spot) if spot > 0 else 0.0,
                strike,
            ),
        )
        pain_value = total_pain[max_pain_strike]

        if spot <= 0:
            return MaxPainAnalysis(
                max_pain=max_pain_strike,
                total_pain=pain_value,
                distance_from_spot=0.0,
                bias=MarketBias.NEUTRAL,
            )

        # Positive means Max Pain is above spot; negative means below spot.
        distance = max_pain_strike - spot

        neutral_distance = max(
            self.config.minimum_neutral_distance,
            spot
            * self.config.neutral_distance_percent
            / 100.0,
        )

        if abs(distance) <= neutral_distance:
            bias = MarketBias.NEUTRAL
        elif distance > 0:
            # Max Pain above spot implies an upward price-magnet pull.
            bias = MarketBias.BULLISH
        else:
            # Max Pain below spot implies a downward price-magnet pull.
            bias = MarketBias.BEARISH

        return MaxPainAnalysis(
            max_pain=max_pain_strike,
            total_pain=pain_value,
            distance_from_spot=distance,
            bias=bias,
        )

    @staticmethod
    def _valid_strikes(
        snapshot: OptionChainSnapshot,
    ) -> list:
        valid = []

        for strike_data in getattr(snapshot, "strikes", []) or []:
            try:
                strike = float(strike_data.strike)
            except (TypeError, ValueError):
                continue

            if not isfinite(strike) or strike <= 0:
                continue

            valid.append(strike_data)

        return valid

    @staticmethod
    def _valid_oi(value: object) -> int:
        try:
            oi = int(float(value or 0))
        except (TypeError, ValueError):
            return 0

        return max(0, oi)

    @staticmethod
    def _valid_spot(value: object) -> float:
        try:
            spot = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

        if not isfinite(spot) or spot <= 0:
            return 0.0
        return spot


__all__ = [
    "MaxPainConfig",
    "MaxPainEngine",
]
