from news_intelligence.market_watch_dashboard_bridge import enrich_dashboard_market_watch


def test_bridge_is_disabled_without_events_and_preserves_report_fields() -> None:
    report = {
        "generated_at": "2026-09-25T09:20:00+05:30",
        "count": 1,
        "rows": [{"symbol": "ABC", "ltp": 100.0, "execution_signal": "UNCHANGED"}],
    }

    enriched = enrich_dashboard_market_watch(report)

    assert enriched["generated_at"] == report["generated_at"]
    assert enriched["count"] == report["count"]
    assert enriched["rows"] == report["rows"]
    assert enriched["news_intelligence"]["enabled"] is False
    assert enriched["news_intelligence"]["paper_signal_only"] is True


def test_bridge_does_not_mutate_report() -> None:
    report = {"rows": [{"symbol": "ABC", "execution_signal": "UNCHANGED"}]}

    enrich_dashboard_market_watch(report)

    assert report == {"rows": [{"symbol": "ABC", "execution_signal": "UNCHANGED"}]}
