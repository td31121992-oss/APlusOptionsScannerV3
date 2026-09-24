"""Pre-market news intelligence and market-shock early-warning components.

The package is intentionally provider-agnostic and paper-signal only.
"""

from .models import NewsEvent, NewsImpact, NewsSource

__all__ = ["NewsEvent", "NewsImpact", "NewsSource"]
