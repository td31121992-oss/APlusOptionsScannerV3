"""
analytics/confidence_engine.py

Confidence aggregation for APlus Options Scanner V3.

Design principles
-----------------
* Aggregate OI direction is the primary market-bias source.
* PCR confirms or conflicts with OI; it does not overwrite OI direction.
* Liquidity is a safety gate, not a source of directional conviction.
* IV, OI concentration, and Max Pain receive limited weights.
* Conflicting or insufficient evidence reduces/caps confidence.
* LOW and POOR liquidity cannot produce actionable confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enums import ConfidenceGrade, MarketBias
from .models import (
    ConfidenceAnalysis,
    IVAnalysis,
    LiquidityAnalysis,
    MaxPainAnalysis,
    OIAnalysis,
    OIConcentrationAnalysis,
    PCRAnalysis,
)


@dataclass(frozen=True, slots=True)
class ConfidenceConfig:
    """Weights, thresholds, penalties, and confidence safety caps."""

    # Weighted-average components. These values should total 1.0.
    oi_weight: float = 0.50
    pcr_weight: float = 0.15
    liquidity_weight: float = 0.20
    concentration_weight: float = 0.08
    iv_weight: float = 0.04
    max_pain_weight: float = 0.03

    bullish_pcr: float = 1.15
    bearish_pcr: float = 0.85

    pcr_conflict_penalty: float = 12.0
    concentration_conflict_penalty: float = 4.0
    max_pain_conflict_penalty: float = 2.0

    no_confirmation_cap: float = 65.0
    one_confirmation_cap: float = 78.0
    neutral_oi_cap: float = 55.0
    static_oi_cap: float = 60.0
    multiple_conflicts_cap: float = 60.0

    excellent_liquidity_cap: float = 100.0
    good_liquidity_cap: float = 88.0
    average_liquidity_cap: float = 74.0
    low_liquidity_cap: float = 60.0
    poor_liquidity_cap: float = 45.0

    def __post_init__(self) -> None:
        weights = (
            self.oi_weight,
            self.pcr_weight,
            self.liquidity_weight,
            self.concentration_weight,
            self.iv_weight,
            self.max_pain_weight,
        )
        if any(weight < 0 for weight in weights):
            raise ValueError("Confidence weights cannot be negative")
        if abs(sum(weights) - 1.0) > 1e-9:
            raise ValueError("Confidence weights must total 1.0")
        if not 0 < self.bearish_pcr < self.bullish_pcr:
            raise ValueError(
                "Expected 0 < bearish_pcr < bullish_pcr"
            )


class ConfidenceEngine:
    """Combine analytics without allowing one indicator to dominate."""

    def __init__(
        self,
        config: ConfidenceConfig | None = None,
    ) -> None:
        self.config = config or ConfidenceConfig()

    def analyze(
        self,
        oi: OIAnalysis,
        pcr: PCRAnalysis,
        liquidity: LiquidityAnalysis,
        iv: IVAnalysis,
        oi_concentration: OIConcentrationAnalysis,
        max_pain: MaxPainAnalysis,
    ) -> ConfidenceAnalysis:
        cfg = self.config
        reasons: list[str] = []

        oi_bias = self._bias(oi.bias)
        final_bias = oi_bias

        oi_score = self._clamp(oi.oi_score)
        liquidity_score = self._clamp(liquidity.score)
        iv_score = self._clamp(iv.iv_score)
        concentration_score = self._clamp(
            oi_concentration.concentration_score
        )

        static_oi_only = self._is_static_oi_only(oi)

        if oi.reason:
            reasons.append(oi.reason)

        if oi_bias == MarketBias.NEUTRAL:
            reasons.append(
                "OI direction is neutral; PCR cannot create a trade bias"
            )
        elif static_oi_only:
            reasons.append(
                f"OI bias is {oi_bias.name.lower()} but is based on "
                "no meaningful interval OI change"
            )
        else:
            reasons.append(
                f"Direction set by aggregate OI: "
                f"{oi_bias.name.lower()} (score {oi_score:.0f})"
            )

        pcr_bias, pcr_strength = self._pcr_bias_and_strength(
            pcr.oi_pcr
        )
        pcr_component, pcr_status = self._alignment_component(
            final_bias,
            pcr_bias,
            pcr_strength,
        )

        confirmations = 0
        conflicts = 0
        penalty = 0.0

        if pcr_status == "confirm":
            confirmations += 1
            reasons.append(
                f"OI PCR {pcr.oi_pcr:.2f} confirms "
                f"{final_bias.name.lower()} bias"
            )
        elif pcr_status == "conflict":
            conflicts += 1
            penalty += cfg.pcr_conflict_penalty
            reasons.append(
                f"OI PCR {pcr.oi_pcr:.2f} conflicts with "
                f"{final_bias.name.lower()} OI bias"
            )
        elif pcr_bias == MarketBias.NEUTRAL:
            reasons.append(f"OI PCR {pcr.oi_pcr:.2f} is neutral")
        else:
            reasons.append(
                f"OI PCR {pcr.oi_pcr:.2f} is directional, "
                "but aggregate OI is neutral"
            )

        concentration_bias = self._bias(
            oi_concentration.bias
        )
        concentration_component, concentration_status = (
            self._alignment_component(
                final_bias,
                concentration_bias,
                concentration_score,
            )
        )

        reasons.append(
            f"OI concentration "
            f"{oi_concentration.concentration_score:.0f}"
        )
        if concentration_status == "confirm":
            confirmations += 1
            reasons.append(
                "OI concentration confirms aggregate OI direction"
            )
        elif concentration_status == "conflict":
            conflicts += 1
            penalty += cfg.concentration_conflict_penalty
            reasons.append(
                "OI concentration conflicts with aggregate OI direction"
            )
        elif concentration_bias == MarketBias.NEUTRAL:
            reasons.append("OI concentration direction is neutral")

        max_pain_bias = self._bias(max_pain.bias)
        max_pain_component, max_pain_status = (
            self._alignment_component(
                final_bias,
                max_pain_bias,
                65.0,
            )
        )

        # Max Pain is deliberately low weight because it is contextual and
        # should not override current OI flow.
        if max_pain_status == "confirm":
            confirmations += 1
            reasons.append(
                f"Max Pain {max_pain.max_pain:.2f} bias agrees "
                "(low weight)"
            )
        elif max_pain_status == "conflict":
            conflicts += 1
            penalty += cfg.max_pain_conflict_penalty
            reasons.append(
                f"Max Pain {max_pain.max_pain:.2f} bias conflicts "
                "(low weight)"
            )
        else:
            reasons.append(
                f"Max Pain {max_pain.max_pain:.2f} is neutral/context only"
            )

        grade_name = self._grade_name(liquidity)
        reasons.append(
            f"Liquidity {grade_name} ({liquidity_score:.0f})"
        )
        reasons.append(
            f"IV {iv.average_iv:.2f} "
            f"(quality score {iv_score:.0f}, low weight)"
        )

        raw_score = (
            oi_score * cfg.oi_weight
            + pcr_component * cfg.pcr_weight
            + liquidity_score * cfg.liquidity_weight
            + concentration_component
            * cfg.concentration_weight
            + iv_score * cfg.iv_weight
            + max_pain_component * cfg.max_pain_weight
        )

        score = raw_score - penalty

        # Evidence caps prevent a numerically high score when independent
        # directional agreement is missing.
        if final_bias == MarketBias.NEUTRAL:
            score = min(score, cfg.neutral_oi_cap)
            reasons.append(
                f"Confidence capped at {cfg.neutral_oi_cap:.0f}: "
                "aggregate OI direction is neutral"
            )
        elif static_oi_only:
            score = min(score, cfg.static_oi_cap)
            reasons.append(
                f"Confidence capped at {cfg.static_oi_cap:.0f}: "
                "no meaningful interval OI confirmation"
            )
        elif conflicts >= 2:
            score = min(score, cfg.multiple_conflicts_cap)
            reasons.append(
                f"Confidence capped at "
                f"{cfg.multiple_conflicts_cap:.0f}: "
                "multiple directional conflicts"
            )
        elif confirmations == 0:
            score = min(score, cfg.no_confirmation_cap)
            reasons.append(
                f"Confidence capped at "
                f"{cfg.no_confirmation_cap:.0f}: "
                "no independent directional confirmation"
            )
        elif confirmations == 1:
            score = min(score, cfg.one_confirmation_cap)
            reasons.append(
                f"Confidence capped at "
                f"{cfg.one_confirmation_cap:.0f}: "
                "only one independent confirmation"
            )

        liquidity_cap = self._liquidity_cap(grade_name)
        if score > liquidity_cap:
            score = liquidity_cap
            reasons.append(
                f"Confidence capped at {liquidity_cap:.0f} "
                f"for {grade_name} liquidity"
            )

        score = round(self._clamp(score), 2)
        grade = self._confidence_grade(score)

        return self._make_analysis(
            score=score,
            grade=grade,
            bias=final_bias,
            reasons=reasons,
        )

    def _pcr_bias_and_strength(
        self,
        value: float,
    ) -> tuple[MarketBias, float]:
        cfg = self.config
        pcr = max(0.0, float(value or 0.0))

        if pcr <= 0:
            return MarketBias.NEUTRAL, 0.0

        if pcr <= cfg.bearish_pcr:
            distance = (
                (cfg.bearish_pcr - pcr)
                / cfg.bearish_pcr
            )
            strength = 60.0 + min(40.0, distance * 40.0)
            return MarketBias.BEARISH, strength

        if pcr >= cfg.bullish_pcr:
            distance = (
                (pcr - cfg.bullish_pcr)
                / cfg.bullish_pcr
            )
            strength = 60.0 + min(40.0, distance * 40.0)
            return MarketBias.BULLISH, strength

        return MarketBias.NEUTRAL, 50.0

    @staticmethod
    def _alignment_component(
        primary_bias: MarketBias,
        secondary_bias: MarketBias,
        secondary_strength: float,
    ) -> tuple[float, str]:
        strength = ConfidenceEngine._clamp(secondary_strength)

        if primary_bias == MarketBias.NEUTRAL:
            return 35.0, "context"

        if secondary_bias == primary_bias:
            return strength, "confirm"

        if secondary_bias == MarketBias.NEUTRAL:
            return 45.0, "neutral"

        return 10.0, "conflict"

    def _liquidity_cap(self, grade_name: str) -> float:
        cfg = self.config
        normalized = grade_name.upper()

        if normalized == "EXCELLENT":
            return cfg.excellent_liquidity_cap
        if normalized == "GOOD":
            return cfg.good_liquidity_cap
        if normalized == "AVERAGE":
            return cfg.average_liquidity_cap
        if normalized == "LOW":
            return cfg.low_liquidity_cap
        return cfg.poor_liquidity_cap

    @staticmethod
    def _grade_name(liquidity: LiquidityAnalysis) -> str:
        grade = getattr(liquidity, "grade", None)
        name = getattr(grade, "name", None)
        if name:
            return str(name).upper()

        value = getattr(grade, "value", grade)
        text = str(value or "POOR").strip().upper()
        if "." in text:
            text = text.rsplit(".", 1)[-1]
        return text or "POOR"

    @staticmethod
    def _is_static_oi_only(oi: OIAnalysis) -> bool:
        """
        Return True only when interval OI evidence is genuinely unavailable.

        ``OIEngine`` may write "static PCR confirms" after a valid interval-OI
        classification. That phrase describes the confirming PCR input; it does
        not mean the OI signal itself is static. Therefore, generic
        ``"static PCR"`` text must never trigger the no-change confidence cap.
        """

        reason = str(getattr(oi, "reason", "") or "").lower()
        call_change = int(
            getattr(oi, "total_call_oi_change", 0) or 0
        )
        put_change = int(
            getattr(oi, "total_put_oi_change", 0) or 0
        )

        explicitly_insignificant = (
            "oi change is not significant" in reason
            or "no significant aggregate oi change" in reason
        )
        no_interval_change = (
            call_change == 0 and put_change == 0
        )

        return explicitly_insignificant or no_interval_change

    @staticmethod
    def _bias(value: Any) -> MarketBias:
        if isinstance(value, MarketBias):
            return value

        text = str(value or "").strip().upper()
        if "." in text:
            text = text.rsplit(".", 1)[-1]

        if text == "BULLISH":
            return MarketBias.BULLISH
        if text == "BEARISH":
            return MarketBias.BEARISH
        return MarketBias.NEUTRAL

    @staticmethod
    def _confidence_grade(score: float) -> ConfidenceGrade:
        if score >= 85:
            return ConfidenceGrade.VERY_HIGH
        if score >= 70:
            return ConfidenceGrade.HIGH
        if score >= 50:
            return ConfidenceGrade.MEDIUM
        if score >= 30:
            return ConfidenceGrade.LOW
        return ConfidenceGrade.VERY_LOW

    @staticmethod
    def _make_analysis(
        *,
        score: float,
        grade: ConfidenceGrade,
        bias: MarketBias,
        reasons: list[str],
    ) -> ConfidenceAnalysis:
        """
        Support both current and older ConfidenceAnalysis model variants.

        The current project model includes ``grade``. The fallback keeps this
        engine import-compatible with a model that omits that field.
        """

        try:
            return ConfidenceAnalysis(
                score=score,
                grade=grade,
                bias=bias,
                reasons=reasons,
            )
        except TypeError as exc:
            if "grade" not in str(exc):
                raise
            return ConfidenceAnalysis(
                score=score,
                bias=bias,
                reasons=reasons,
            )

    @staticmethod
    def _clamp(value: float) -> float:
        return min(100.0, max(0.0, float(value or 0.0)))


__all__ = [
    "ConfidenceConfig",
    "ConfidenceEngine",
]
