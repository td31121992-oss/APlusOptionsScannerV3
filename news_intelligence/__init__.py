"""Pre-market news intelligence and market-shock early-warning components.

The package is intentionally provider-agnostic and paper-signal only.
"""

from .collector import NewsCollector, StaticNewsCollector
from .models import NewsEvent, NewsImpact, NewsSource
from .report_writer import NewsReportWriter
from .shock_engine import MarketShockEarlyWarning, MarketShockWarning

__all__ = [
    "MarketShockEarlyWarning",
    "MarketShockWarning",
    "NewsCollector",
    "NewsEvent",
    "NewsImpact",
    "NewsReportWriter",
    "NewsSource",
    "StaticNewsCollector",
]
