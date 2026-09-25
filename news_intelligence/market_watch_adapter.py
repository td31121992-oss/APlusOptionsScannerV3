"""Non-invasive adapter for attaching news intelligence to market-watch rows.

The adapter is intentionally provider-neutral and paper-signal-only. It does
not fetch quotes, place orders, or mutate scanner execution decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .models import NewsEvent
from .risk_engine import PreMarketRiskEngine
from .shock_engine import MarketShockEarlyWarning, MarketShockWarning


@dataclass(frozen=True, slots=True)
class MarketWatchNewsAnnotation:
    """Serializable news context for one market-watch symbol."""

    symbol: str
    event_count: int
    highest_impact: str
    risk_level: str
    risk_score: int
    shock_level: str
    shock_score: int
    paper_signal_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "news_event_count": self.event_count,
            "news_highest_impact": self.highest_impact,
            "news_risk_level": self.risk_level,
            "news_risk_score": self.risk_score,
            "market_shock_level": self.shock_level,
            "market_shock_score": self.shock_score,
            "news_paper_signal_only": self.paper_signal_only,
        }


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def annotate_market_watch(
    rows: Sequence[Mapping[str, Any]],
    events: Sequence[NewsEvent],
    *,
    risk_engine: PreMarketRiskEngine | None = None,
    shock_engine: MarketShockEarlyWarning | None = None,
) -> list[dict[str, Any]]:
    """Return copied market-watch rows with explainable news annotations.

    Rows without a symbol are copied unchanged. Existing row keys are
    preserved, and no trading or execution fields are changed.
    """

    risk = risk_engine or PreMarketRiskEngine()
    shock = shock_engine or MarketShockEarlyWarning(risk)
    normalized_events = tuple(events)
    grouped: dict[str, list[NewsEvent]] = {}
    for event in normalized_events:
        for symbol in event.symbols:
            key = _normalize_symbol(symbol)
            if key:
                grouped.setdefault(key, []).append(event)

    output: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        symbol = _normalize_symbol(row.get("symbol"))
        matching = tuple(grouped.get(symbol, ()))
        if not symbol or not matching:
            output.append(copied)
            continue

        risks = tuple(risk.classify(event) for event in matching)
        highest = max(matching, key=lambda event: (event.impact.value, event.confidence))
        warning: MarketShockWarning = shock.evaluate(matching)
        annotation = MarketWatchNewsAnnotation(
            symbol=symbol,
            event_count=len(matching),
            highest_impact=highest.impact.value,
            risk_level=max(risks, key=lambda item: item.score).level,
            risk_score=max(item.score for item in risks),
            shock_level=warning.level,
            shock_score=warning.score,
        )
        copied.update(annotation.to_dict())
        output.append(copied)

    return output
