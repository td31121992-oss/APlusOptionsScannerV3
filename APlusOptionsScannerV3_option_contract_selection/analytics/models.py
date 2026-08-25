"""
analytics/models.py
Shared dataclasses for APlus Options Scanner V3.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .enums import (
    ConfidenceGrade,
    LiquidityGrade,
    MarketBias,
    OptionSide,
    RecommendationType,
    SignalType,
)


@dataclass(slots=True)
class OptionLeg:
    security_id: str
    side: OptionSide
    strike: float
    ltp: float
    oi: int
    volume: int
    iv: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    previous_oi: int = 0
    previous_close: float = 0.0
    oi_change: int = 0
    oi_change_percent: float = 0.0
    price_change: float = 0.0
    price_change_percent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StrikeData:
    strike: float
    call: OptionLeg | None = None
    put: OptionLeg | None = None

    def legs(self):
        if self.call:
            yield self.call
        if self.put:
            yield self.put


@dataclass(slots=True)
class OptionChainSnapshot:
    symbol: str
    underlying_security_id: str
    expiry: str
    underlying_ltp: float
    captured_at: str
    strikes: list[StrikeData] = field(default_factory=list)

    def all_legs(self):
        for strike in self.strikes:
            yield from strike.legs()

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "underlying_security_id": self.underlying_security_id,
            "expiry": self.expiry,
            "underlying_ltp": self.underlying_ltp,
            "captured_at": self.captured_at,
            "strikes": [
                {
                    "strike": item.strike,
                    "call": item.call.to_dict() if item.call else None,
                    "put": item.put.to_dict() if item.put else None,
                }
                for item in self.strikes
            ],
        }


@dataclass(slots=True)
class MarketStructure:
    atm_strike: float
    call_wall: float
    put_wall: float
    support: float
    resistance: float


@dataclass(slots=True)
class OIAnalysis:
    total_call_oi: int = 0
    total_put_oi: int = 0
    total_call_oi_change: int = 0
    total_put_oi_change: int = 0
    max_call_oi: int = 0
    max_call_oi_strike: float = 0.0
    max_put_oi: int = 0
    max_put_oi_strike: float = 0.0
    support: float = 0.0
    resistance: float = 0.0
    oi_score: float = 0.0
    bias: MarketBias = MarketBias.NEUTRAL
    signal: SignalType = SignalType.NEUTRAL
    reason: str = ""


@dataclass(slots=True)
class PCRAnalysis:
    oi_pcr: float
    volume_pcr: float


@dataclass(slots=True)
class LiquidityAnalysis:
    score: float
    average_spread: float
    grade: LiquidityGrade = LiquidityGrade.POOR
    average_volume: float = 0.0


@dataclass(slots=True)
class StrategySignal:
    symbol: str
    bias: MarketBias
    strength: float
    confidence: float
    recommendation: RecommendationType = RecommendationType.HOLD
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RankedStock:
    rank: int
    symbol: str
    score: float
    signal: StrategySignal


@dataclass(slots=True)
class OptionContractSelection:
    """Executable option-buy plan selected from the live option chain."""

    exchange_segment: str
    security_id: str
    trading_symbol: str
    display_name: str
    expiry: str
    option_type: str
    transaction: str
    strike: float

    ltp: float
    bid: float
    ask: float
    limit_price: float
    tick_size: float

    oi: int
    volume: int
    iv: float
    spread_percent: float

    lot_size: int
    lots: int
    quantity: int

    premium_per_lot: float
    total_premium: float

    stop_loss: float
    target1: float
    target2: float
    target3: float

    risk_per_unit: float
    risk_per_lot: float
    total_risk: float

    selection_score: float
    selection_reason: str


@dataclass(slots=True)
class TradeRecommendation:
    """Underlying signal plus an executable long-option contract plan."""

    symbol: str
    recommendation: RecommendationType
    entry: float
    stop_loss: float
    target1: float
    target2: float
    target3: float
    confidence: float
    option_contract: OptionContractSelection | None = None


@dataclass(slots=True)
class ScanStatistics:
    started_at: datetime
    completed_at: datetime | None = None
    universe: int = 0
    succeeded: int = 0
    failed: int = 0


@dataclass(slots=True)
class ScannerReport:
    statistics: ScanStatistics
    rankings: list[RankedStock] = field(default_factory=list)
    recommendations: list[TradeRecommendation] = field(default_factory=list)


@dataclass(slots=True)
class WritingAnalysis:
    call_writing: float = 0.0
    put_writing: float = 0.0
    call_unwinding: float = 0.0
    put_unwinding: float = 0.0
    strongest_call_strike: float = 0.0
    strongest_put_strike: float = 0.0
    writing_score: float = 0.0
    bias: MarketBias = MarketBias.NEUTRAL


@dataclass(slots=True)
class MomentumAnalysis:
    price_change_percent: float = 0.0
    oi_change_percent: float = 0.0
    score: float = 0.0
    bias: MarketBias = MarketBias.NEUTRAL


@dataclass(slots=True)
class IVAnalysis:
    atm_iv: float = 0.0
    average_iv: float = 0.0
    highest_iv: float = 0.0
    lowest_iv: float = 0.0
    iv_skew: float = 0.0
    iv_score: float = 0.0
    bias: MarketBias = MarketBias.NEUTRAL


@dataclass(slots=True)
class OIConcentrationAnalysis:
    top_call_walls: list[tuple[float, int]] = field(default_factory=list)
    top_put_walls: list[tuple[float, int]] = field(default_factory=list)
    total_call_oi: int = 0
    total_put_oi: int = 0
    call_concentration: float = 0.0
    put_concentration: float = 0.0
    strongest_call_wall: float = 0.0
    strongest_put_wall: float = 0.0
    concentration_score: float = 0.0
    bias: MarketBias = MarketBias.NEUTRAL


@dataclass(slots=True)
class MaxPainAnalysis:
    max_pain: float = 0.0
    total_pain: float = 0.0
    distance_from_spot: float = 0.0
    bias: MarketBias = MarketBias.NEUTRAL


@dataclass(slots=True)
class ConfidenceAnalysis:
    score: float = 0.0
    grade: ConfidenceGrade = ConfidenceGrade.VERY_LOW
    bias: MarketBias = MarketBias.NEUTRAL
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PipelineAnalysis:
    market_structure: MarketStructure
    oi: OIAnalysis
    writing: WritingAnalysis
    pcr: PCRAnalysis
    liquidity: LiquidityAnalysis
    momentum: MomentumAnalysis
    iv: IVAnalysis
    oi_concentration: OIConcentrationAnalysis
    max_pain: MaxPainAnalysis
    confidence: ConfidenceAnalysis
