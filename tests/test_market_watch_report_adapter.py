from datetime import datetime, timezone

from news_intelligence.market_watch_report_adapter import enrich_market_watch_report
from news_intelligence.models import NewsEvent, NewsImpact


def _event(symbol: str) -> NewsEvent:
    return NewsEvent(
        event_id=f"event-{symbol}",
        headline=f"{symbol} update",
        summary="Synthetic integration event",
        symbols=(symbol,),
        impact=NewsImpact.HIGH,
        confidence=0.95,
        is_verified=True,
        detected_at=datetime.now(timezone.utc),
    )


def test_report_adapter_preserves_metadata_and_execution_fields() -> None:
    report = {
        "generated_at": "2026-09-25T09:20:00+05:30",
        "count": 1,
        "rows": [{"symbol": "ABC", "ltp": 100.0, "execution_signal": "UNCHANGED"}],
        "sectors": ["Financials"],
    }

    enriched = enrich_market_watch_report(report, [_event("ABC")])

    assert enriched["generated_at"] == report["generated_at"]
    assert enriched["count"] == report["count"]
    assert enriched["sectors"] == report["sectors"]
    assert enriched["rows"][0]["execution_signal"] == "UNCHANGED"
    assert enriched["rows"][0]["news_highest_impact"] == "HIGH"
    assert enriched["news_intelligence"]["paper_signal_only"] is True


def test_report_adapter_does_not_mutate_input_report() -> None:
    report = {"rows": [{"symbol": "ABC", "execution_signal": "UNCHANGED"}]}
    original = {"rows": [dict(report["rows"][0])]}

    enrich_market_watch_report(report, [_event("ABC")])

    assert report == original
