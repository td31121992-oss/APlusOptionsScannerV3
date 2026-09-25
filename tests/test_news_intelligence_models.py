from datetime import datetime, timezone

import pytest

from news_intelligence.models import NewsEvent, NewsImpact, NewsSource
from news_intelligence.verification import ConservativeSourceVerifier


def test_news_event_is_paper_only_and_serializable() -> None:
    event = NewsEvent(
        event_id="evt-1",
        headline="Regulatory proposal",
        summary="A material proposal was published.",
        symbols=("PBFINTECH",),
        impact=NewsImpact.HIGH,
        confidence=0.8,
        detected_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    payload = event.to_dict()

    assert payload["paper_signal_only"] is True
    assert payload["symbols"] == ["PBFINTECH"]
    assert payload["impact"] == "HIGH"


def test_unverified_source_does_not_become_verified() -> None:
    event = NewsEvent(
        event_id="evt-2",
        headline="Unverified report",
        summary="Pending confirmation.",
        symbols=("ABC",),
        source=NewsSource(
            publisher="Example",
            url="https://example.com/news",
            verification_status="UNVERIFIED",
        ),
    )

    verified = ConservativeSourceVerifier().verify(event)

    assert verified.is_verified is False


def test_confidence_range_is_enforced() -> None:
    with pytest.raises(ValueError):
        NewsEvent(
            event_id="evt-3",
            headline="Invalid confidence",
            summary="Invalid test event.",
            symbols=("ABC",),
            confidence=1.1,
        )
