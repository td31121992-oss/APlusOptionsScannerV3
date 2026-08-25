"""
analytics/oi_concentration_engine.py

Open Interest Concentration Engine

Calculates:

• Top 5 Call OI Walls
• Top 5 Put OI Walls
• OI Concentration %
• Strongest Support
• Strongest Resistance
• Dominant Side
• Concentration Score
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import MarketBias
from .models import OptionChainSnapshot


@dataclass(slots=True)
class OIConcentrationAnalysis:
    top_call_walls: list[tuple[float, int]]
    top_put_walls: list[tuple[float, int]]

    total_call_oi: int
    total_put_oi: int

    call_concentration: float
    put_concentration: float

    strongest_call_wall: float
    strongest_put_wall: float

    concentration_score: float

    bias: MarketBias = MarketBias.NEUTRAL


class OIConcentrationEngine:

    def analyze(
        self,
        snapshot: OptionChainSnapshot,
    ) -> OIConcentrationAnalysis:

        call_data: list[tuple[float, int]] = []
        put_data: list[tuple[float, int]] = []

        total_call = 0
        total_put = 0

        for strike in snapshot.strikes:

            if strike.call is not None:

                total_call += strike.call.oi

                call_data.append(
                    (
                        strike.strike,
                        strike.call.oi,
                    )
                )

            if strike.put is not None:

                total_put += strike.put.oi

                put_data.append(
                    (
                        strike.strike,
                        strike.put.oi,
                    )
                )

        call_data.sort(
            key=lambda x: x[1],
            reverse=True,
        )

        put_data.sort(
            key=lambda x: x[1],
            reverse=True,
        )

        top_calls = call_data[:5]
        top_puts = put_data[:5]

        call_top = sum(v for _, v in top_calls)
        put_top = sum(v for _, v in top_puts)

        call_pct = (
            call_top / total_call * 100
            if total_call
            else 0.0
        )

        put_pct = (
            put_top / total_put * 100
            if total_put
            else 0.0
        )

        score = max(call_pct, put_pct)

        if put_pct > call_pct + 5:
            bias = MarketBias.BULLISH

        elif call_pct > put_pct + 5:
            bias = MarketBias.BEARISH

        else:
            bias = MarketBias.NEUTRAL

        return OIConcentrationAnalysis(
            top_call_walls=top_calls,
            top_put_walls=top_puts,
            total_call_oi=total_call,
            total_put_oi=total_put,
            call_concentration=round(call_pct, 2),
            put_concentration=round(put_pct, 2),
            strongest_call_wall=top_calls[0][0] if top_calls else 0.0,
            strongest_put_wall=top_puts[0][0] if top_puts else 0.0,
            concentration_score=round(score, 2),
            bias=bias,
        )