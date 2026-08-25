"""
analytics/pcr_engine.py

Put-Call Ratio analytics.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import OptionChainSnapshot, PCRAnalysis


@dataclass(slots=True)
class PCRThresholds:
    bullish: float = 1.20
    bearish: float = 0.80


class PCREngine:
    def __init__(self, thresholds: PCRThresholds | None = None) -> None:
        self.thresholds = thresholds or PCRThresholds()

    def analyze(self, snapshot: OptionChainSnapshot) -> PCRAnalysis:
        call_oi = 0
        put_oi = 0
        call_vol = 0
        put_vol = 0

        for strike in snapshot.strikes:
            if strike.call:
                call_oi += strike.call.oi
                call_vol += strike.call.volume
            if strike.put:
                put_oi += strike.put.oi
                put_vol += strike.put.volume

        oi_pcr = (put_oi / call_oi) if call_oi else 0.0
        volume_pcr = (put_vol / call_vol) if call_vol else 0.0

        return PCRAnalysis(
            oi_pcr=round(oi_pcr, 4),
            volume_pcr=round(volume_pcr, 4),
        )
