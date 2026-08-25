"""
analytics/pipeline.py

Analytics integration pipeline for APlus Options Scanner V3.

The pipeline delegates aggregate Open Interest classification to ``OIEngine``
instead of maintaining a second, conflicting OI implementation inside this
file. All remaining analytics engines are executed in a stable order and their
results are combined by ``ConfidenceEngine``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .confidence_engine import ConfidenceEngine
from .iv_engine import IVEngine
from .liquidity_engine import LiquidityEngine
from .market_structure import MarketStructureEngine
from .max_pain_engine import MaxPainEngine
from .models import (
    ConfidenceAnalysis,
    IVAnalysis,
    LiquidityAnalysis,
    MarketStructure,
    MaxPainAnalysis,
    OIAnalysis,
    OIConcentrationAnalysis,
    OptionChainSnapshot,
    PCRAnalysis,
)
from .momentum_engine import MomentumAnalysis, MomentumEngine
from .oi_concentration_engine import OIConcentrationEngine
from .oi_engine import OIEngine
from .pcr_engine import PCREngine


class AnalyticsPipelineError(RuntimeError):
    """Raised when analytics cannot be produced for a snapshot."""


@dataclass(slots=True)
class AnalyticsResult:
    """Complete analytics output for one underlying option-chain snapshot."""

    symbol: str
    expiry: str
    underlying_ltp: float

    market_structure: MarketStructure
    oi: OIAnalysis
    pcr: PCRAnalysis
    liquidity: LiquidityAnalysis
    momentum: MomentumAnalysis
    iv: IVAnalysis
    oi_concentration: OIConcentrationAnalysis
    max_pain: MaxPainAnalysis
    confidence: ConfidenceAnalysis

    previous_snapshot_available: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnalyticsPipelineConfig:
    """
    Backward-compatible pipeline configuration.

    Aggregate OI thresholds now belong to ``OIThresholds`` in
    ``analytics.oi_engine``. These legacy fields are retained so existing code
    that constructs ``AnalyticsPipelineConfig`` does not break.
    """

    bullish_oi_ratio: float = 1.10
    bearish_oi_ratio: float = 0.90
    strong_change_ratio: float = 1.20
    neutral_score: float = 40.0
    directional_score: float = 65.0
    strong_directional_score: float = 85.0


class AnalyticsPipeline:
    """Run all analytics engines for one normalized option-chain snapshot."""

    def __init__(
        self,
        *,
        market_structure_engine: MarketStructureEngine | None = None,
        oi_engine: OIEngine | None = None,
        pcr_engine: PCREngine | None = None,
        liquidity_engine: LiquidityEngine | None = None,
        momentum_engine: MomentumEngine | None = None,
        iv_engine: IVEngine | None = None,
        oi_concentration_engine: OIConcentrationEngine | None = None,
        max_pain_engine: MaxPainEngine | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        config: AnalyticsPipelineConfig | None = None,
    ) -> None:
        self.market_structure_engine = (
            market_structure_engine or MarketStructureEngine()
        )
        self.oi_engine = oi_engine or OIEngine()
        self.pcr_engine = pcr_engine or PCREngine()
        self.liquidity_engine = liquidity_engine or LiquidityEngine()
        self.momentum_engine = momentum_engine or MomentumEngine()
        self.iv_engine = iv_engine or IVEngine()
        self.oi_concentration_engine = (
            oi_concentration_engine or OIConcentrationEngine()
        )
        self.max_pain_engine = max_pain_engine or MaxPainEngine()
        self.confidence_engine = confidence_engine or ConfidenceEngine()

        # Retained for backwards compatibility and future pipeline-level flags.
        self.config = config or AnalyticsPipelineConfig()

    def analyze(
        self,
        snapshot: OptionChainSnapshot,
        *,
        previous_snapshot_available: bool = False,
        previous_underlying_ltp: float | None = None,
    ) -> AnalyticsResult:
        """Analyze one normalized option-chain snapshot."""

        self._validate_snapshot(snapshot)

        market_structure = self.market_structure_engine.analyze(snapshot)

        # OIEngine is now the single source of truth for aggregate OI direction.
        oi = self.oi_engine.analyze(
            snapshot,
            market_structure=market_structure,
            previous_underlying_ltp=previous_underlying_ltp,
        )

        pcr = self.pcr_engine.analyze(snapshot)
        liquidity = self.liquidity_engine.analyze(snapshot)

        momentum = self.momentum_engine.analyze(
            snapshot,
            previous_underlying_ltp=previous_underlying_ltp,
        )

        iv = self.iv_engine.analyze(snapshot)
        oi_concentration = self.oi_concentration_engine.analyze(snapshot)
        max_pain = self.max_pain_engine.analyze(snapshot)

        confidence = self.confidence_engine.analyze(
            oi=oi,
            pcr=pcr,
            liquidity=liquidity,
            iv=iv,
            oi_concentration=oi_concentration,
            max_pain=max_pain,
        )

        return AnalyticsResult(
            symbol=snapshot.symbol,
            expiry=snapshot.expiry,
            underlying_ltp=snapshot.underlying_ltp,
            market_structure=market_structure,
            oi=oi,
            pcr=pcr,
            liquidity=liquidity,
            momentum=momentum,
            iv=iv,
            oi_concentration=oi_concentration,
            max_pain=max_pain,
            confidence=confidence,
            previous_snapshot_available=previous_snapshot_available,
            metadata={
                "strike_count": len(snapshot.strikes),
                "option_leg_count": sum(
                    1 for _ in snapshot.all_legs()
                ),
                "previous_snapshot_available": (
                    previous_snapshot_available
                ),
                "previous_underlying_ltp": previous_underlying_ltp,
                "oi_engine": type(self.oi_engine).__name__,
            },
        )

    @staticmethod
    def _validate_snapshot(snapshot: OptionChainSnapshot) -> None:
        if not str(snapshot.symbol).strip():
            raise AnalyticsPipelineError(
                "Snapshot symbol cannot be blank"
            )

        if not str(snapshot.expiry).strip():
            raise AnalyticsPipelineError(
                f"Snapshot expiry is missing for {snapshot.symbol}"
            )

        if snapshot.underlying_ltp <= 0:
            raise AnalyticsPipelineError(
                f"Underlying LTP must be positive for {snapshot.symbol}"
            )

        if not snapshot.strikes:
            raise AnalyticsPipelineError(
                f"No option-chain strikes available for {snapshot.symbol}"
            )

        option_leg_count = sum(1 for _ in snapshot.all_legs())
        if option_leg_count == 0:
            raise AnalyticsPipelineError(
                f"No option legs available for {snapshot.symbol}"
            )


__all__ = [
    "AnalyticsPipeline",
    "AnalyticsPipelineConfig",
    "AnalyticsPipelineError",
    "AnalyticsResult",
]
