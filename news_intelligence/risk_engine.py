"""Pre-market risk classification for news-derived paper warnings."""

from __future__ import annotations

from dataclasses import dataclass

from .models import NewsEvent, NewsImpact


@dataclass(frozen=True, slots=True)
class PreMarketRisk:
    event_id: str
    level: str
    score: int
    reasons: tuple[str, ...]
    paper_signal_only: bool = True

    def __post_init__(self) -> None:
        if self.level not in {"WATCH", "ELEVATED", "HIGH", "CRITICAL"}:
            raise ValueError("unsupported risk level")
        if not 0 <= self.score <= 100:
            raise ValueError("risk score must be between 0 and 100")
        if not self.paper_signal_only:
            raise ValueError("risk classification must remain paper-signal only")


class PreMarketRiskEngine:
    """Convert verified news metadata into a transparent risk watch level."""

    _BASE_SCORE = {
        NewsImpact.UNKNOWN: 10,
        NewsImpact.LOW: 25,
        NewsImpact.MEDIUM: 50,
        NewsImpact.HIGH: 75,
        NewsImpact.CRITICAL: 90,
    }

    def classify(self, event: NewsEvent) -> PreMarketRisk:
        score = self._BASE_SCORE[event.impact]
        reasons: list[str] = [f"impact={event.impact.value}"]

        if event.is_verified:
            score += 5
            reasons.append("source_verified")
        else:
            reasons.append("source_unverified")

        if event.pre_market:
            reasons.append("pre_market_event")
        else:
            score = max(0, score - 10)
            reasons.append("non_pre_market_event")

        if event.confidence < 0.50:
            score = min(score, 40)
            reasons.append("low_confidence_cap")
        elif event.confidence >= 0.85:
            score += 5
            reasons.append("high_confidence")

        score = max(0, min(100, score))
        if score >= 85:
            level = "CRITICAL"
        elif score >= 65:
            level = "HIGH"
        elif score >= 40:
            level = "ELEVATED"
        else:
            level = "WATCH"

        return PreMarketRisk(
            event_id=event.event_id,
            level=level,
            score=score,
            reasons=tuple(reasons),
        )
