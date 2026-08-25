"""
analytics/iv_engine.py

Implied Volatility Analysis Engine
"""

from __future__ import annotations

from .enums import MarketBias
from .models import (
    IVAnalysis,
    OptionChainSnapshot,
)


class IVEngine:
    """
    Calculates:

    • ATM IV
    • Average IV
    • Highest IV
    • Lowest IV
    • IV Skew
    • IV Score
    """

    def analyze(
        self,
        snapshot: OptionChainSnapshot,
    ) -> IVAnalysis:

        if not snapshot.strikes:
            return IVAnalysis()

        iv_values: list[float] = []

        atm_iv = 0.0
        nearest_distance = float("inf")

        highest_iv = 0.0
        lowest_iv = float("inf")

        call_sum = 0.0
        put_sum = 0.0
        call_count = 0
        put_count = 0

        spot = snapshot.underlying_ltp

        for strike in snapshot.strikes:

            distance = abs(strike.strike - spot)

            if strike.call is not None:

                iv = max(0.0, strike.call.iv)

                iv_values.append(iv)

                highest_iv = max(highest_iv, iv)
                lowest_iv = min(lowest_iv, iv)

                call_sum += iv
                call_count += 1

                if distance < nearest_distance:
                    nearest_distance = distance
                    atm_iv = iv

            if strike.put is not None:

                iv = max(0.0, strike.put.iv)

                iv_values.append(iv)

                highest_iv = max(highest_iv, iv)
                lowest_iv = min(lowest_iv, iv)

                put_sum += iv
                put_count += 1

                if distance < nearest_distance:
                    nearest_distance = distance
                    atm_iv = iv

        if not iv_values:
            return IVAnalysis()

        average_iv = sum(iv_values) / len(iv_values)

        if lowest_iv == float("inf"):
            lowest_iv = 0.0

        call_avg = call_sum / call_count if call_count else 0.0
        put_avg = put_sum / put_count if put_count else 0.0

        iv_skew = call_avg - put_avg

        if average_iv >= 35:
            iv_score = 90.0
        elif average_iv >= 28:
            iv_score = 75.0
        elif average_iv >= 22:
            iv_score = 60.0
        elif average_iv >= 16:
            iv_score = 45.0
        else:
            iv_score = 25.0

        if iv_skew > 2:
            bias = MarketBias.BULLISH
        elif iv_skew < -2:
            bias = MarketBias.BEARISH
        else:
            bias = MarketBias.NEUTRAL

        return IVAnalysis(
            atm_iv=round(atm_iv, 2),
            average_iv=round(average_iv, 2),
            highest_iv=round(highest_iv, 2),
            lowest_iv=round(lowest_iv, 2),
            iv_skew=round(iv_skew, 2),
            iv_score=round(iv_score, 2),
            bias=bias,
        )