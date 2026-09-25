import json

import pytest

from news_intelligence.event_source import load_news_events


def test_load_news_events_accepts_wrapped_document(tmp_path) -> None:
    path = tmp_path / "events.json"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "event_id": "evt-1",
                        "headline": "ABC update",
                        "summary": "Verified update",
                        "symbols": ["abc"],
                        "impact": "high",
                        "detected_at": "2026-09-25T09:00:00+05:30",
                        "confidence": 0.9,
                        "is_verified": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    events = load_news_events(path)

    assert len(events) == 1
    assert events[0].symbols == ("ABC",)
    assert events[0].impact.value == "HIGH"
    assert events[0].paper_signal_only is True


def test_load_news_events_rejects_invalid_confidence(tmp_path) -> None:
    path = tmp_path / "events.json"
    path.write_text(
        json.dumps(
            [
                {
                    "event_id": "evt-1",
                    "headline": "ABC update",
                    "symbols": ["ABC"],
                    "confidence": 1.5,
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="confidence"):
        load_news_events(path)


def test_load_news_events_rejects_empty_symbols(tmp_path) -> None:
    path = tmp_path / "events.json"
    path.write_text(
        json.dumps(
            [
                {
                    "event_id": "evt-empty-symbols",
                    "headline": "Missing symbol update",
                    "symbols": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="symbols"):
        load_news_events(path)


def test_load_news_events_rejects_non_object_event(tmp_path) -> None:
    path = tmp_path / "events.json"
    path.write_text(json.dumps(["not-an-event"]), encoding="utf-8")

    with pytest.raises(ValueError, match="each news event"):
        load_news_events(path)
