"""
analytics/oi_engine.py

Aggregate Open Interest analytics for APlus Options Scanner V3.

The engine treats OI change as the primary directional input and uses the
absolute Put/Call OI ratio only as confirmation. This prevents a low or high
static PCR from forcing every symbol into the same direction.

Important aggregate interpretations
-----------------------------------
* Call OI rising + Put OI falling: bearish pressure.
* Call OI falling + Put OI rising: bullish pressure.
* Both sides rising: option writing on both sides; direction requires clear
  dominance, otherwise the result is neutral.
* Both sides falling: broad unwinding; direction requires both clear dominance
  and confirming movement in the underlying, otherwise the result is neutral.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enums import MarketBias, SignalType
from .models import OIAnalysis, OptionChainSnapshot, OptionLeg


@dataclass(frozen=True, slots=True)
class OIThresholds:
    """Thresholds used by aggregate and per-leg OI classification."""

    min_oi_change_absolute: int = 100
    min_oi_change_percent: float = 0.10
    min_price_change_percent: float = 0.25

    dominance_ratio: float = 1.35
    bullish_pcr: float = 1.15
    bearish_pcr: float = 0.85

    neutral_score: float = 35.0
    static_directional_score: float = 48.0
    directional_score: float = 62.0
    strong_directional_score: float = 76.0
    maximum_score: float = 85.0

    def __post_init__(self) -> None:
        if self.min_oi_change_absolute < 0:
            raise ValueError("min_oi_change_absolute cannot be negative")
        if self.min_oi_change_percent < 0:
            raise ValueError("min_oi_change_percent cannot be negative")
        if self.min_price_change_percent < 0:
            raise ValueError("min_price_change_percent cannot be negative")
        if self.dominance_ratio <= 1.0:
            raise ValueError("dominance_ratio must be greater than 1")
        if not 0 < self.bearish_pcr < self.bullish_pcr:
            raise ValueError(
                "Expected 0 < bearish_pcr < bullish_pcr"
            )
        if self.maximum_score <= 0:
            raise ValueError("maximum_score must be positive")


@dataclass(frozen=True, slots=True)
class LegOIAnalysis:
    """Classification result for one option leg."""

    signal: SignalType
    score: float
    reason: str


class OIEngine:
    """Calculate aggregate call/put OI statistics and directional bias."""

    def __init__(self, thresholds: OIThresholds | None = None) -> None:
        self.thresholds = thresholds or OIThresholds()

    # ------------------------------------------------------------------
    # Public aggregate API
    # ------------------------------------------------------------------

    def analyze(
        self,
        snapshot: OptionChainSnapshot,
        *,
        market_structure: Any | None = None,
        previous_underlying_ltp: float | None = None,
    ) -> OIAnalysis:
        """Return one aggregate ``OIAnalysis`` for the complete snapshot."""

        call_legs = [
            strike.call
            for strike in snapshot.strikes
            if strike.call is not None
        ]
        put_legs = [
            strike.put
            for strike in snapshot.strikes
            if strike.put is not None
        ]

        total_call_oi = sum(max(0, int(leg.oi)) for leg in call_legs)
        total_put_oi = sum(max(0, int(leg.oi)) for leg in put_legs)

        total_call_change = sum(int(leg.oi_change) for leg in call_legs)
        total_put_change = sum(int(leg.oi_change) for leg in put_legs)

        previous_call_oi = self._previous_total(call_legs, total_call_oi)
        previous_put_oi = self._previous_total(put_legs, total_put_oi)

        call_change_percent = self._percent(
            total_call_change,
            previous_call_oi,
        )
        put_change_percent = self._percent(
            total_put_change,
            previous_put_oi,
        )

        max_call = max(call_legs, key=lambda leg: leg.oi, default=None)
        max_put = max(put_legs, key=lambda leg: leg.oi, default=None)

        oi_pcr = (
            total_put_oi / total_call_oi
            if total_call_oi > 0
            else 0.0
        )

        spot_change_percent = self._spot_change_percent(
            snapshot.underlying_ltp,
            previous_underlying_ltp,
        )

        bias, signal, score, interpretation = self._classify_aggregate(
            oi_pcr=oi_pcr,
            call_change=total_call_change,
            put_change=total_put_change,
            call_change_percent=call_change_percent,
            put_change_percent=put_change_percent,
            spot_change_percent=spot_change_percent,
        )

        support = float(
            getattr(market_structure, "support", 0.0) or 0.0
        )
        resistance = float(
            getattr(market_structure, "resistance", 0.0) or 0.0
        )

        reason_parts = [
            f"Put/Call OI ratio {oi_pcr:.2f}",
            (
                f"Call OI change {total_call_change:+d} "
                f"({call_change_percent:+.2f}%)"
            ),
            (
                f"Put OI change {total_put_change:+d} "
                f"({put_change_percent:+.2f}%)"
            ),
            interpretation,
        ]
        if spot_change_percent is not None:
            reason_parts.insert(
                3,
                f"Spot change {spot_change_percent:+.2f}%",
            )

        return OIAnalysis(
            total_call_oi=total_call_oi,
            total_put_oi=total_put_oi,
            total_call_oi_change=total_call_change,
            total_put_oi_change=total_put_change,
            max_call_oi=int(max_call.oi) if max_call is not None else 0,
            max_call_oi_strike=(
                float(max_call.strike) if max_call is not None else 0.0
            ),
            max_put_oi=int(max_put.oi) if max_put is not None else 0,
            max_put_oi_strike=(
                float(max_put.strike) if max_put is not None else 0.0
            ),
            support=support,
            resistance=resistance,
            oi_score=round(
                min(self.thresholds.maximum_score, max(0.0, score)),
                2,
            ),
            bias=bias,
            signal=signal,
            reason="; ".join(reason_parts),
        )

    def analyze_snapshot(
        self,
        snapshot: OptionChainSnapshot,
        *,
        market_structure: Any | None = None,
        previous_underlying_ltp: float | None = None,
    ) -> OIAnalysis:
        """Compatibility alias for callers using the older method name."""

        return self.analyze(
            snapshot,
            market_structure=market_structure,
            previous_underlying_ltp=previous_underlying_ltp,
        )

    # ------------------------------------------------------------------
    # Optional per-leg API
    # ------------------------------------------------------------------

    def analyze_leg(self, leg: OptionLeg) -> LegOIAnalysis:
        """Classify one option leg from its premium and OI movement."""

        cfg = self.thresholds

        oi_significant = (
            abs(int(leg.oi_change)) >= cfg.min_oi_change_absolute
            and abs(float(leg.oi_change_percent))
            >= cfg.min_oi_change_percent
        )
        price_up = (
            float(leg.price_change_percent)
            >= cfg.min_price_change_percent
        )
        price_down = (
            float(leg.price_change_percent)
            <= -cfg.min_price_change_percent
        )

        if not oi_significant or not (price_up or price_down):
            return LegOIAnalysis(
                signal=SignalType.NEUTRAL,
                score=0.0,
                reason="No significant combined OI and premium change",
            )

        oi_up = leg.oi_change > 0

        if oi_up and price_up:
            return LegOIAnalysis(
                signal=SignalType.LONG_BUILDUP,
                score=76.0,
                reason="OI up and premium up",
            )

        if oi_up and price_down:
            return LegOIAnalysis(
                signal=SignalType.SHORT_BUILDUP,
                score=72.0,
                reason="OI up and premium down",
            )

        if not oi_up and price_down:
            return LegOIAnalysis(
                signal=SignalType.LONG_UNWINDING,
                score=60.0,
                reason="OI down and premium down",
            )

        return LegOIAnalysis(
            signal=SignalType.SHORT_COVERING,
            score=64.0,
            reason="OI down and premium up",
        )

    # ------------------------------------------------------------------
    # Aggregate classification
    # ------------------------------------------------------------------

    def _classify_aggregate(
        self,
        *,
        oi_pcr: float,
        call_change: int,
        put_change: int,
        call_change_percent: float,
        put_change_percent: float,
        spot_change_percent: float | None,
    ) -> tuple[MarketBias, SignalType, float, str]:
        cfg = self.thresholds

        call_significant = self._is_significant(
            call_change,
            call_change_percent,
        )
        put_significant = self._is_significant(
            put_change,
            put_change_percent,
        )

        # No meaningful change: static PCR can provide only a weak indication.
        if not call_significant and not put_significant:
            if oi_pcr >= cfg.bullish_pcr:
                return (
                    MarketBias.BULLISH,
                    SignalType.PUT_WRITING,
                    cfg.static_directional_score,
                    "Static PCR is bullish; OI change is not significant",
                )
            if 0 < oi_pcr <= cfg.bearish_pcr:
                return (
                    MarketBias.BEARISH,
                    SignalType.CALL_WRITING,
                    cfg.static_directional_score,
                    "Static PCR is bearish; OI change is not significant",
                )
            return (
                MarketBias.NEUTRAL,
                SignalType.NEUTRAL,
                cfg.neutral_score,
                "No significant aggregate OI change",
            )

        call_direction = self._direction(call_change, call_significant)
        put_direction = self._direction(put_change, put_significant)

        # Opposite movements give the clearest directional information.
        if call_direction > 0 and put_direction < 0:
            result = (
                MarketBias.BEARISH,
                SignalType.CALL_WRITING,
                cfg.strong_directional_score,
                "Call writing and Put unwinding indicate bearish pressure",
            )
            return self._apply_pcr_confirmation(result, oi_pcr)

        if call_direction < 0 and put_direction > 0:
            result = (
                MarketBias.BULLISH,
                SignalType.PUT_WRITING,
                cfg.strong_directional_score,
                "Call unwinding and Put writing indicate bullish pressure",
            )
            return self._apply_pcr_confirmation(result, oi_pcr)

        # Both sides rising means writing on both sides. Require dominance.
        if call_direction > 0 and put_direction > 0:
            dominance = self._dominant_side(
                abs(call_change_percent),
                abs(put_change_percent),
            )
            if dominance == "call":
                result = (
                    MarketBias.BEARISH,
                    SignalType.CALL_WRITING,
                    cfg.directional_score,
                    "Both sides added OI; Call writing clearly dominates",
                )
                return self._apply_pcr_confirmation(result, oi_pcr)
            if dominance == "put":
                result = (
                    MarketBias.BULLISH,
                    SignalType.PUT_WRITING,
                    cfg.directional_score,
                    "Both sides added OI; Put writing clearly dominates",
                )
                return self._apply_pcr_confirmation(result, oi_pcr)
            return (
                MarketBias.NEUTRAL,
                SignalType.NEUTRAL,
                cfg.neutral_score,
                "Both sides added OI without clear dominance",
            )

        # Both sides falling is broad unwinding. Do not infer a strong direction
        # without both dominance and confirming movement in the underlying.
        if call_direction < 0 and put_direction < 0:
            dominance = self._dominant_side(
                abs(call_change_percent),
                abs(put_change_percent),
            )

            if (
                dominance == "call"
                and spot_change_percent is not None
                and spot_change_percent >= cfg.min_price_change_percent
            ):
                result = (
                    MarketBias.BULLISH,
                    SignalType.SHORT_COVERING,
                    cfg.directional_score,
                    "Both sides unwound; dominant Call unwinding is confirmed by rising spot",
                )
                return self._apply_pcr_confirmation(result, oi_pcr)

            if (
                dominance == "put"
                and spot_change_percent is not None
                and spot_change_percent <= -cfg.min_price_change_percent
            ):
                result = (
                    MarketBias.BEARISH,
                    SignalType.LONG_UNWINDING,
                    cfg.directional_score,
                    "Both sides unwound; dominant Put unwinding is confirmed by falling spot",
                )
                return self._apply_pcr_confirmation(result, oi_pcr)

            return (
                MarketBias.NEUTRAL,
                SignalType.NEUTRAL,
                cfg.neutral_score,
                "Both Call and Put OI unwound without directional confirmation",
            )

        # One significant side only.
        if call_direction > 0:
            result = (
                MarketBias.BEARISH,
                SignalType.CALL_WRITING,
                cfg.directional_score,
                "Significant Call OI addition indicates bearish pressure",
            )
            return self._apply_pcr_confirmation(result, oi_pcr)

        if call_direction < 0:
            result = (
                MarketBias.BULLISH,
                SignalType.SHORT_COVERING,
                cfg.directional_score,
                "Significant Call OI unwinding indicates bullish pressure",
            )
            return self._apply_pcr_confirmation(result, oi_pcr)

        if put_direction > 0:
            result = (
                MarketBias.BULLISH,
                SignalType.PUT_WRITING,
                cfg.directional_score,
                "Significant Put OI addition indicates bullish support",
            )
            return self._apply_pcr_confirmation(result, oi_pcr)

        if put_direction < 0:
            result = (
                MarketBias.BEARISH,
                SignalType.LONG_UNWINDING,
                cfg.directional_score,
                "Significant Put OI unwinding indicates weakening support",
            )
            return self._apply_pcr_confirmation(result, oi_pcr)

        return (
            MarketBias.NEUTRAL,
            SignalType.NEUTRAL,
            cfg.neutral_score,
            "Aggregate OI is inconclusive",
        )

    def _apply_pcr_confirmation(
        self,
        result: tuple[MarketBias, SignalType, float, str],
        oi_pcr: float,
    ) -> tuple[MarketBias, SignalType, float, str]:
        bias, signal, score, reason = result
        cfg = self.thresholds

        pcr_bias = MarketBias.NEUTRAL
        if oi_pcr >= cfg.bullish_pcr:
            pcr_bias = MarketBias.BULLISH
        elif 0 < oi_pcr <= cfg.bearish_pcr:
            pcr_bias = MarketBias.BEARISH

        if pcr_bias == bias:
            score += 5.0
            reason += "; static PCR confirms"
        elif pcr_bias != MarketBias.NEUTRAL and pcr_bias != bias:
            score -= 12.0
            reason += "; static PCR conflicts"

        return (
            bias,
            signal,
            min(cfg.maximum_score, max(cfg.neutral_score, score)),
            reason,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_significant(
        self,
        absolute_change: int,
        percent_change: float,
    ) -> bool:
        cfg = self.thresholds
        return (
            abs(absolute_change) >= cfg.min_oi_change_absolute
            and abs(percent_change) >= cfg.min_oi_change_percent
        )

    def _dominant_side(
        self,
        call_magnitude: float,
        put_magnitude: float,
    ) -> str | None:
        cfg = self.thresholds

        if call_magnitude <= 0 and put_magnitude <= 0:
            return None
        if put_magnitude <= 0:
            return "call"
        if call_magnitude <= 0:
            return "put"

        if call_magnitude / put_magnitude >= cfg.dominance_ratio:
            return "call"
        if put_magnitude / call_magnitude >= cfg.dominance_ratio:
            return "put"
        return None

    @staticmethod
    def _direction(change: int, significant: bool) -> int:
        if not significant or change == 0:
            return 0
        return 1 if change > 0 else -1

    @staticmethod
    def _previous_total(
        legs: list[OptionLeg],
        current_total: int,
    ) -> int:
        explicit_previous = sum(
            max(0, int(getattr(leg, "previous_oi", 0) or 0))
            for leg in legs
        )
        if explicit_previous > 0:
            return explicit_previous

        total_change = sum(int(leg.oi_change) for leg in legs)
        inferred_previous = current_total - total_change
        return max(0, inferred_previous)

    @staticmethod
    def _percent(change: int, previous_value: int) -> float:
        if previous_value <= 0:
            return 0.0
        return (change / previous_value) * 100.0

    @staticmethod
    def _spot_change_percent(
        current_ltp: float,
        previous_ltp: float | None,
    ) -> float | None:
        if previous_ltp is None or previous_ltp <= 0:
            return None
        return ((current_ltp - previous_ltp) / previous_ltp) * 100.0


__all__ = [
    "LegOIAnalysis",
    "OIEngine",
    "OIThresholds",
]
