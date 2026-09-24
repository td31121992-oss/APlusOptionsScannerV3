"""Pre-market news intelligence and market-shock early-warning components.

The package is intentionally provider-agnostic and paper-signal only.
"""

from .collector import NewsCollector, StaticNewsCollector
from .models import NewsEvent, NewsImpact, NewsSource
from .report_writer import NewsReportWriter

__all__ = [
    "NewsCollector",
    "NewsEvent",
    "NewsImpact",
    "NewsReportWriter",
    "NewsSource",
    "StaticNewsCollector",
]
