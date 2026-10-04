from __future__ import annotations

import unittest
from unittest.mock import patch

import stock_analysis_tab


class StockAnalysisIntelligenceIntegrationTests(unittest.TestCase):
    def test_analysis_payload_includes_read_only_explainable_context(self) -> None:
        market = {"symbol": "ABC", "sector": "Banking", "direction": "UP", "from_open_pct": 1.0}
        points = [{"time": "10:00", "ltp": 100.0}, {"time": "10:01", "ltp": 100.2}]
        with (
            patch.object(stock_analysis_tab, "_market_row", return_value=market),
            patch.object(stock_analysis_tab, "_load_points", return_value=points),
            patch.object(stock_analysis_tab, "_latest_candidate", return_value={}),
            patch.object(stock_analysis_tab, "_read_market_watch", return_value={"generated_at": "2026-09-29T10:00:00+05:30"}),
        ):
            payload = stock_analysis_tab.analysis_payload("2026-09-29", "abc")

        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["trading_engine_untouched"])
        self.assertFalse(payload["intelligence"]["causality_claimed"])
        self.assertEqual(payload["symbol"], "ABC")
        titles = {section["title"] for section in payload["intelligence"]["sections"]}
        self.assertTrue({"MARKET CONTEXT", "TECHNICAL CONTEXT", "SECTOR CONTEXT",
                         "OPTIONS INTELLIGENCE", "NEWS / CATALYST", "WHY THIS STOCK IS MOVING",
                         "HOLDING THESIS", "INVALIDATION / RISK"}.issubset(titles))
        self.assertIn('id="intelligence"', stock_analysis_tab.STOCK_ANALYSIS_HTML)


if __name__ == "__main__":
    unittest.main()
