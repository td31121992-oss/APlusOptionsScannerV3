"""Safe bridge for optional dashboard market-watch enrichment.

The dashboard can call this boundary without coupling its HTTP handler to a
news provider. With no events, the original report values remain unchanged;
when events are supplied, enrichment is additive and paper-signal-only.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .market_watch_report_adapter import enrich_market_watch_report
from .models import NewsEvent


def enrich_dashboard_market_watch(
    report: Mapping[str, Any],
    events: Sequence[NewsEvent] = (),
) -> dict[str, Any]:
    """Return a safe copied dashboard report with optional news context."""

    enriched = enrich_market_watch_report(report, events)
    enriched.setdefault("news_intelligence", {})
    enriched["news_intelligence"].setdefault("enabled", bool(events))
    enriched["news_intelligence"]["paper_signal_only"] = True
    return enriched
