from datetime import datetime, timezone

from news_intelligence.market_watch_adapter import annotate_market_watch
from news_intelligence.models import NewsEvent, NewsImpact


def _event(event_id: str, symbol: str, impact: NewsImpact, confidence: float) -> NewsEvent:
    return NewsEvent(
        event_id=event_id,
        headline=f"{symbol} update",
        summary="Test event",
        symbols=(symbol,),
        impact=impact,
        confidence=confidence,
        is_verified=True,
        detected_at=datetime.now(timezone.utc),
    )


def test_annotation_preserves_rows_and_adds_news_context() -> None:
    rows = [{"symbol": "ABC", "ltp": 100.0, "execution_signal": "UNCHANGED"}, {"symbol": "XYZ"}]
    events = [_event("e1", "abc", NewsImpact.HIGH, 0.9)]

    result = annotate_market_watch(rows, events)

    assert result[0]["execution_signal"] == "UNCHANGED"
    assert result[0]["news_event_count"] == 1
    assert result[0]["news_highest_impact"] == "HIGH"
    assert result[0]["news_paper_signal_only"] is True
    assert result[1] == rows[1]


def test_unmatched_row_is_copied_without_news_fields() -> None:
    rows = [{"symbol": "XYZ", "ltp": 20.0}]

    result = annotate_market_watch(rows, [_event("e1", "ABC", NewsImpact.CRITICAL, 1.0)])

    assert result == rows
