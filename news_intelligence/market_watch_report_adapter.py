"""Read-only integration boundary for the F&O market-watch report.

The adapter preserves report metadata and execution-related row fields while
adding paper-only news intelligence to copied rows. It does not read quotes,
place orders, or alter scanner state.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .market_watch_payload import build_market_watch_payload
from .models import NewsEvent


def enrich_market_watch_report(
    report: Mapping[str, Any],
    events: Sequence[NewsEvent],
) -> dict[str, Any]:
    """Return a copied report with paper-only news context attached."""

    rows = report.get("rows", ())
    if not isinstance(rows, (list, tuple)):
        rows = ()

    enriched = dict(report)
    payload = build_market_watch_payload(rows, events)
    enriched["rows"] = payload["rows"]
    enriched["news_intelligence"] = {
        "paper_signal_only": True,
        "news_event_count": payload["news_event_count"],
        "shock_level_counts": payload["shock_level_counts"],
        "risk_level_counts": payload["risk_level_counts"],
    }
    return enriched
