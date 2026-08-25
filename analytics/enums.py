"""
analytics/enums.py

APlus Options Scanner V3
Production Enums

Author: OpenAI
"""

from __future__ import annotations

from enum import Enum


class OptionSide(str, Enum):
    """Option contract side."""

    CALL = "CALL"
    PUT = "PUT"


class MarketBias(str, Enum):
    """Overall market bias."""

    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


class Trend(str, Enum):
    """Underlying price trend."""

    STRONG_UP = "STRONG_UP"
    UP = "UP"
    SIDEWAYS = "SIDEWAYS"
    DOWN = "DOWN"
    STRONG_DOWN = "STRONG_DOWN"


class SignalType(str, Enum):
    """OI based signal."""

    LONG_BUILDUP = "LONG_BUILDUP"
    SHORT_BUILDUP = "SHORT_BUILDUP"
    LONG_UNWINDING = "LONG_UNWINDING"
    SHORT_COVERING = "SHORT_COVERING"
    CALL_WRITING = "CALL_WRITING"
    PUT_WRITING = "PUT_WRITING"
    CALL_UNWINDING = "CALL_UNWINDING"
    PUT_UNWINDING = "PUT_UNWINDING"
    NEUTRAL = "NEUTRAL"


class RecommendationType(str, Enum):
    """Trade recommendation."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    AVOID = "AVOID"


class LiquidityGrade(str, Enum):
    """Liquidity classification."""

    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    AVERAGE = "AVERAGE"
    LOW = "LOW"
    POOR = "POOR"


class ConfidenceGrade(str, Enum):
    """Confidence bucket."""

    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"


class OIAction(str, Enum):
    """Open Interest action."""

    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    UNCHANGED = "UNCHANGED"


class WritingType(str, Enum):
    """Writing classification."""

    AGGRESSIVE_CALL_WRITING = "AGGRESSIVE_CALL_WRITING"
    CALL_WRITING = "CALL_WRITING"
    AGGRESSIVE_PUT_WRITING = "AGGRESSIVE_PUT_WRITING"
    PUT_WRITING = "PUT_WRITING"
    NONE = "NONE"


class PriceDirection(str, Enum):
    """Price movement."""

    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class MomentumStrength(str, Enum):
    """Momentum strength."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


class SupportResistanceType(str, Enum):
    """OI wall type."""

    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class ScannerStatus(str, Enum):
    """Scanner execution status."""

    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


__all__ = [
    "OptionSide",
    "MarketBias",
    "Trend",
    "SignalType",
    "RecommendationType",
    "LiquidityGrade",
    "ConfidenceGrade",
    "OIAction",
    "WritingType",
    "PriceDirection",
    "MomentumStrength",
    "SupportResistanceType",
    "ScannerStatus",
]