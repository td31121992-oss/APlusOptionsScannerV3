"""Build a safe, serializable payload for market-watch presentation.

This module is deliberately separate from the live dashboard and execution
path. It enriches copied rows with paper-only news context and exposes a
small summary suitable for a future dashboard/API integration.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from .market_watch_adapter import annotate_market_watch
from .models import NewsEvent


def build_market_watch_payload(
    rows: Sequence[Mapping[str, Any]],
    events: Sequence[NewsEvent],
) -> dict[str, Any]:
    """Return annotated rows and explainable paper-only summary data."""

    annotated_rows = annotate_market_watch(rows, events)
    shock_levels = Counter(
        str(row.get("market_shock_level"))
        for row in annotated_rows
        if row.get("market_shock_level")
    )
    risk_levels = Counter(
        str(row.get("news_risk_level"))
        for row in annotated_rows
        if row.get("news_risk_level")
    )

    return {
        "paper_signal_only": True,
        "row_count": len(annotated_rows),
        "news_event_count": len(events),
        "shock_level_counts": dict(sorted(shock_levels.items())),
        "risk_level_counts": dict(sorted(risk_levels.items())),
        "rows": annotated_rows,
    }
