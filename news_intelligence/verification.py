"""Source verification interfaces for news intelligence."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from .models import NewsEvent


class SourceVerifier(Protocol):
    """Interface implemented by a future live-source verification adapter."""

    def verify(self, event: NewsEvent) -> NewsEvent:
        """Return the event with verification metadata updated."""


class ConservativeSourceVerifier:
    """Safe default: only explicitly supplied verified sources are accepted."""

    def verify(self, event: NewsEvent) -> NewsEvent:
        source = event.source
        if source is None:
            return event
        verified = source.verification_status.strip().upper() == "VERIFIED"
        return replace(event, is_verified=verified)
