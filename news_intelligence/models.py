"""Provider-neutral models for verified market-news intelligence.

These models describe observations only. They do not place orders or produce
broker instructions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class NewsImpact(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class NewsSource:
    """A source record retained for auditability and later verification."""

    publisher: str
    url: str
    published_at: datetime | None = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_type: str = "UNKNOWN"
    verification_status: str = "UNVERIFIED"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("published_at", "retrieved_at"):
            value = payload[key]
            payload[key] = value.isoformat() if value else None
        return payload


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """Normalized news event used by downstream impact and risk engines."""

    event_id: str
    headline: str
    summary: str
    symbols: tuple[str, ...]
    impact: NewsImpact = NewsImpact.UNKNOWN
    event_type: str = "UNKNOWN"
    source: NewsSource | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pre_market: bool = True
    confidence: float = 0.0
    is_verified: bool = False
    paper_signal_only: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if not self.headline.strip():
            raise ValueError("headline must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.paper_signal_only:
            raise ValueError("news intelligence must remain paper-signal only")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["impact"] = self.impact.value
        payload["detected_at"] = self.detected_at.isoformat()
        payload["source"] = self.source.to_dict() if self.source else None
        payload["symbols"] = list(self.symbols)
        return payload
