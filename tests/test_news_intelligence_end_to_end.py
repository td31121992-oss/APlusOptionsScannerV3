from pathlib import Path

from news_intelligence import build_market_watch_payload, load_news_events


FIXTURE = Path(__file__).parent / "fixtures" / "news_events_sample.json"


def test_sample_news_event_flows_into_market_watch_payload() -> None:
    events = load_news_events(FIXTURE)
    rows = [
        {
            "symbol": "ABC",
            "ltp": 125.0,
            "direction": "UP",
            "execution_allowed": False,
        },
        {
            "symbol": "UNMATCHED",
            "ltp": 80.0,
            "direction": "DOWN",
            "execution_allowed": True,
        },
    ]

    payload = build_market_watch_payload(rows, events)

    assert payload["paper_signal_only"] is True
    assert payload["row_count"] == 2
    assert payload["news_event_count"] == 1
    assert payload["shock_level_counts"]
    assert payload["risk_level_counts"]["CRITICAL"] == 1

    matched = payload["rows"][0]
    assert matched["symbol"] == "ABC"
    assert matched["news_event_count"] == 1
    assert matched["news_highest_impact"] == "CRITICAL"
    assert matched["news_paper_signal_only"] is True
    assert matched["execution_allowed"] is False

    unmatched = payload["rows"][1]
    assert unmatched == rows[1]
    assert rows[0]["execution_allowed"] is False
    assert rows[1]["execution_allowed"] is True
