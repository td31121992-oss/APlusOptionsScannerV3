from datetime import datetime, timezone
import json

from news_intelligence.collector import StaticNewsCollector
from news_intelligence.models import NewsEvent, NewsImpact, NewsSource
from news_intelligence.report_writer import NewsReportWriter


def _event() -> NewsEvent:
    now = datetime.now(timezone.utc)
    return NewsEvent(
        event_id="evt-test-1",
        headline="Regulatory proposal affects PB Fintech",
        summary="Test event",
        symbols=("PBFINTECH",),
        impact=NewsImpact.HIGH,
        event_type="REGULATORY",
        source=NewsSource(
            publisher="Test Publisher",
            url="https://example.com/event",
            published_at=now,
            retrieved_at=now,
            source_type="TEST",
            verification_status="VERIFIED",
        ),
        detected_at=now,
        pre_market=True,
        confidence=0.9,
        is_verified=True,
    )


def test_static_collector_is_deterministic() -> None:
    event = _event()
    assert tuple(StaticNewsCollector((event,)).collect()) == (event,)


def test_report_writer_is_explicitly_paper_only(tmp_path) -> None:
    target = NewsReportWriter(tmp_path).write("dry_run", events=(_event(),))
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["paper_signal_only"] is True
    assert payload["events"][0]["event_id"] == "evt-test-1"
