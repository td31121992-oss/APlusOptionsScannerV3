from datetime import datetime, timezone

from news_intelligence.market_watch_payload import build_market_watch_payload
from news_intelligence.models import NewsEvent, NewsImpact


def _event(symbol: str) -> NewsEvent:
    return NewsEvent(
        event_id=f"event-{symbol}",
        headline=f"{symbol} regulatory update",
        summary="Synthetic contract-test event",
        symbols=(symbol,),
        impact=NewsImpact.HIGH,
        confidence=0.9,
        is_verified=True,
        detected_at=datetime.now(timezone.utc),
    )


def test_payload_preserves_dashboard_market_watch_fields() -> None:
    row = {
        "symbol": "ABC",
        "sector": "Financials",
        "open_0915": 100.0,
        "ltp": 103.0,
        "previous_close": 101.0,
        "gap_pct": 1.0,
        "from_open_pct": 3.0,
        "from_prev_close_pct": 1.98,
        "day_high": 104.0,
        "day_low": 99.0,
        "range_position_pct": 80.0,
        "direction": "UP",
        "execution_signal": "PAPER_ONLY_UNCHANGED",
    }

    payload = build_market_watch_payload([row], [_event("ABC")])
    enriched = payload["rows"][0]

    for key, value in row.items():
        assert enriched[key] == value
    assert enriched["news_highest_impact"] == "HIGH"
    assert enriched["news_paper_signal_only"] is True
    assert payload["paper_signal_only"] is True


def test_unmatched_dashboard_rows_are_not_enriched_or_mutated() -> None:
    row = {
        "symbol": "XYZ",
        "ltp": 50.0,
        "execution_signal": "NO_CHANGE",
    }
    original = dict(row)

    payload = build_market_watch_payload([row], [_event("ABC")])

    assert payload["rows"] == [original]
    assert row == original
