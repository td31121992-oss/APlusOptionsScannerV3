"""Explainable mapping from news events to affected market symbols.

This module is deliberately deterministic and paper-only. It does not infer
trade instructions and does not call a broker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import NewsEvent, NewsImpact


@dataclass(frozen=True, slots=True)
class ImpactAssessment:
    event_id: str
    symbol: str
    direction: str
    severity: NewsImpact
    rationale: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    paper_signal_only: bool = True

    def __post_init__(self) -> None:
        if not self.paper_signal_only:
            raise ValueError("impact assessments must remain paper-signal only")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.direction not in {"BULLISH", "BEARISH", "MIXED", "UNKNOWN"}:
            raise ValueError("unsupported impact direction")


class CompanyImpactEngine:
    """Map explicitly supplied symbols to explainable impact assessments.

    Symbol mapping is intentionally explicit. Automatic entity resolution can
    be added later behind a separately tested provider/alias registry.
    """

    def assess(
        self,
        event: NewsEvent,
        *,
        symbol_directions: dict[str, str] | None = None,
        rationale: Iterable[str] = (),
    ) -> tuple[ImpactAssessment, ...]:
        directions = symbol_directions or {}
        assessments: list[ImpactAssessment] = []
        for raw_symbol in event.symbols:
            symbol = raw_symbol.strip().upper()
            if not symbol:
                continue
            direction = directions.get(symbol, "UNKNOWN").upper()
            if direction not in {"BULLISH", "BEARISH", "MIXED", "UNKNOWN"}:
                direction = "UNKNOWN"
            assessments.append(
                ImpactAssessment(
                    event_id=event.event_id,
                    symbol=symbol,
                    direction=direction,
                    severity=event.impact,
                    rationale=tuple(rationale),
                    confidence=event.confidence,
                )
            )
        return tuple(assessments)
