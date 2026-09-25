"""Provider-neutral collection interfaces for normalized news events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from .models import NewsEvent


class NewsCollector(Protocol):
    """Interface implemented by future RSS, API, or feed adapters."""

    def collect(self) -> Iterable[NewsEvent]:
        """Return normalized events without placing orders."""
        ...


@dataclass(frozen=True, slots=True)
class StaticNewsCollector:
    """Deterministic collector useful for dry-runs and unit tests."""

    events: tuple[NewsEvent, ...] = ()

    def __init__(self, events: Iterable[NewsEvent] = ()) -> None:
        object.__setattr__(self, "events", tuple(events))

    def collect(self) -> tuple[NewsEvent, ...]:
        return self.events
