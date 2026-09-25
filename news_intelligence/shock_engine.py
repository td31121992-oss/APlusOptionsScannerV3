"""Transparent market-shock early-warning calculations.

This module produces paper signals only. It does not place orders, call a
broker, or modify the existing scanner execution path.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .models import NewsEvent, NewsImpact
from .risk_engine import PreMarketRisk, PreMarketRiskEngine


@dataclass(frozen=True, slots=True)
class MarketShockWarning:
    """Explainable warning generated from a group of related news events."""

    symbols: tuple[str, ...]
    event_ids: tuple[str, ...]
    level: str
    score: int
    reasons: tuple[str, ...]
    paper_signal_only: bool = True

    def __post_init__(self) -> None:
        if self.level not in {"NONE", "WATCH", "ELEVATED", "HIGH", "CRITICAL"}:
            raise ValueError("unsupported shock warning level")
        if not 0 <= self.score <= 100:
            raise ValueError("shock score must be between 0 and 100")
        if not self.paper_signal_only:
            raise ValueError("shock warnings must remain paper-signal only")


class MarketShockEarlyWarning:
    """Aggregate news risks into a conservative, explainable warning."""

    def __init__(self, risk_engine: PreMarketRiskEngine | None = None) -> None:
        self._risk_engine = risk_engine or PreMarketRiskEngine()

    def evaluate(self, events: tuple[NewsEvent, ...] | list[NewsEvent]) -> MarketShockWarning:
        normalized = tuple(events)
        if not normalized:
            return MarketShockWarning((), (), "NONE", 0, ("no_events",))

        risks: tuple[PreMarketRisk, ...] = tuple(
            self._risk_engine.classify(event) for event in normalized
        )
        symbols = tuple(sorted({symbol for event in normalized for symbol in event.symbols}))
        event_ids = tuple(event.event_id for event in normalized)
        reasons: list[str] = [f"event_count={len(normalized)}"]

        max_score = max(risk.score for risk in risks)
        average_score = round(sum(risk.score for risk in risks) / len(risks))
        critical_count = sum(risk.level == "CRITICAL" for risk in risks)
        high_or_critical_count = sum(risk.level in {"HIGH", "CRITICAL"} for risk in risks)
        symbol_counts = Counter(symbol for event in normalized for symbol in event.symbols)
        repeated_symbols = tuple(sorted(symbol for symbol, count in symbol_counts.items() if count >= 2))

        score = max(max_score, average_score)
        if high_or_critical_count >= 2:
            score += 10
            reasons.append("multiple_high_or_critical_events")
        if critical_count >= 1:
            score += 5
            reasons.append("critical_event_present")
        if repeated_symbols:
            score += 5
            reasons.append("repeated_symbol_coverage=" + ",".join(repeated_symbols))
        if len(normalized) >= 3:
            score += 5
            reasons.append("event_cluster")

        score = min(100, max(0, score))
        if score >= 85:
            level = "CRITICAL"
        elif score >= 65:
            level = "HIGH"
        elif score >= 40:
            level = "ELEVATED"
        elif score > 0:
            level = "WATCH"
        else:
            level = "NONE"

        reasons.append(f"max_risk_score={max_score}")
        reasons.append(f"average_risk_score={average_score}")
        return MarketShockWarning(
            symbols=symbols,
            event_ids=event_ids,
            level=level,
            score=score,
            reasons=tuple(reasons),
        )
