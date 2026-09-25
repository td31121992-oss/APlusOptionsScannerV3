from news_intelligence.models import NewsEvent, NewsImpact
from news_intelligence.shock_engine import MarketShockEarlyWarning


def _event(event_id: str, impact: NewsImpact, confidence: float = 0.9) -> NewsEvent:
    return NewsEvent(
        event_id=event_id,
        headline=f"Headline {event_id}",
        summary="Summary",
        symbols=("NSE:TEST",),
        impact=impact,
        confidence=confidence,
        is_verified=True,
    )


def test_empty_event_set_returns_none_warning() -> None:
    warning = MarketShockEarlyWarning().evaluate([])
    assert warning.level == "NONE"
    assert warning.score == 0
    assert warning.reasons == ("no_events",)


def test_repeated_high_impact_events_raise_warning() -> None:
    warning = MarketShockEarlyWarning().evaluate(
        [
            _event("E1", NewsImpact.HIGH),
            _event("E2", NewsImpact.CRITICAL),
        ]
    )
    assert warning.level in {"HIGH", "CRITICAL"}
    assert warning.score >= 85
    assert "multiple_high_or_critical_events" in warning.reasons
    assert "repeated_symbol_coverage=NSE:TEST" in warning.reasons
    assert warning.paper_signal_only is True
