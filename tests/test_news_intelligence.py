from datetime import datetime, timezone
from pathlib import Path

from news_intelligence import news_context, write_jsonl


def test_news_context_excludes_future_and_old_events(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    write_jsonl(
        [
            {"symbols": ["RELIANCE"], "title": "Positive result",
             "published_at": "2026-10-05T08:00:00+00:00", "direction": "BULLISH",
             "impact": "HIGH", "confidence": 0.9, "source_type": "COMPANY"},
            {"symbols": ["RELIANCE"], "title": "Future event",
             "published_at": "2026-10-05T12:00:00+00:00", "direction": "BEARISH",
             "impact": "HIGH", "confidence": 0.9, "source_type": "COMPANY"},
            {"symbols": ["RELIANCE"], "title": "Old event",
             "published_at": "2026-10-01T08:00:00+00:00", "direction": "NEUTRAL",
             "impact": "LOW", "confidence": 0.5, "source_type": "NEWS"},
        ],
        path,
    )
    result = news_context(
        "RELIANCE",
        as_of=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
        max_age_hours=24,
    )
    assert result["data_status"] == "AVAILABLE"
    assert len(result["events"]) == 1
    assert result["events"][0]["title"] == "Positive result"


def test_unknown_symbol_is_safe() -> None:
    result = news_context("")
    assert result["ok"] is False
    assert result["events"] == []
