from datetime import datetime, timezone

from news_intelligence.market_watch_payload import build_market_watch_payload
from news_intelligence.models import NewsEvent, NewsImpact


def _event(event_id: str, symbol: str, impact: NewsImpact) -> NewsEvent:
    return NewsEvent(
        event_id=event_id,
        headline=f"{symbol} update",
        summary="Test event",
        symbols=(symbol,),
        impact=impact,
        confidence=0.95,
        is_verified=True,
        detected_at=datetime.now(timezone.utc),
    )


def test_payload_preserves_rows_and_builds_summary() -> None:
    rows = [{"symbol": "ABC", "ltp": 100.0}, {"symbol": "XYZ", "ltp": 50.0}]
    events = [_event("e1", "ABC", NewsImpact.CRITICAL)]

    payload = build_market_watch_payload(rows, events)

    assert payload["paper_signal_only"] is True
    assert payload["row_count"] == 2
    assert payload["news_event_count"] == 1
    assert payload["rows"][0]["ltp"] == 100.0
    assert payload["rows"][0]["news_highest_impact"] == "CRITICAL"
    assert payload["rows"][1] == rows[1]
    assert payload["shock_level_counts"] == {"CRITICAL": 1}


def test_payload_does_not_mutate_input_rows() -> None:
    rows = [{"symbol": "ABC", "execution_signal": "UNCHANGED"}]
    original = [dict(row) for row in rows]

    build_market_watch_payload(rows, [_event("e1", "ABC", NewsImpact.HIGH)])

    assert rows == original
