"""Controlled JSON input for normalized, paper-only news events.

This source intentionally reads local structured data only. It does not fetch
external feeds, place orders, or alter scanner execution state.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import NewsEvent, NewsImpact, NewsSource


def _datetime(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO-8601 string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event(payload: dict[str, Any]) -> NewsEvent:
    symbols = payload.get("symbols")
    if (
        not isinstance(symbols, (list, tuple))
        or not symbols
        or not all(isinstance(item, str) and item.strip() for item in symbols)
    ):
        raise ValueError("symbols must be a non-empty list of strings")

    source_payload = payload.get("source")
    source = None
    if source_payload is not None:
        if not isinstance(source_payload, dict):
            raise ValueError("source must be an object")
        source = NewsSource(
            publisher=str(source_payload.get("publisher", "")),
            url=str(source_payload.get("url", "")),
            published_at=(
                _datetime(source_payload["published_at"], field_name="published_at")
                if source_payload.get("published_at")
                else None
            ),
            source_type=str(source_payload.get("source_type", "UNKNOWN")),
            verification_status=str(source_payload.get("verification_status", "UNVERIFIED")),
        )

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")

    return NewsEvent(
        event_id=str(payload["event_id"]),
        headline=str(payload["headline"]),
        summary=str(payload.get("summary", "")),
        symbols=tuple(item.strip().upper() for item in symbols),
        impact=NewsImpact(str(payload.get("impact", "UNKNOWN")).upper()),
        event_type=str(payload.get("event_type", "UNKNOWN")),
        source=source,
        detected_at=(
            _datetime(payload["detected_at"], field_name="detected_at")
            if payload.get("detected_at")
            else datetime.now().astimezone()
        ),
        pre_market=bool(payload.get("pre_market", True)),
        confidence=float(payload.get("confidence", 0.0)),
        is_verified=bool(payload.get("is_verified", False)),
        paper_signal_only=True,
        metadata=metadata,
    )


def load_news_events(path: str | Path) -> tuple[NewsEvent, ...]:
    """Load and validate a JSON array or an object containing ``events``."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("events", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("news event document must be a list or an object with events")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("each news event must be an object")
    return tuple(_event(item) for item in items)
