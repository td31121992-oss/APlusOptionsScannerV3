from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_movement_intelligence import build_why_moving


class StockMovementIntelligenceTests(unittest.TestCase):
    def test_combines_local_evidence_and_keeps_causality_qualified(self) -> None:
        day = "2026-09-29"
        now = datetime(2026, 9, 29, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            (reports / "fno_market_watch_latest.json").write_text(json.dumps({
                "generated_at": "2026-09-29T10:29:00+05:30",
                "rows": [
                    {"symbol": "ABC", "sector": "Banking", "from_open_pct": 1.5},
                    {"symbol": "XYZ", "sector": "Banking", "from_open_pct": 0.5},
                ],
            }), encoding="utf-8")
            options_root = root / "options"
            option_day = options_root / day
            option_day.mkdir(parents=True)
            fields = ["captured_at", "symbol", "expiry", "spot", "strike", "side", "oi", "volume", "iv"]
            with (option_day / "option_chain_rows.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows([
                    {"captured_at": "2026-09-29T10:20:00+05:30", "symbol": "ABC", "spot": 100, "strike": 100, "side": "CE", "oi": 80, "volume": 20, "iv": 18},
                    {"captured_at": "2026-09-29T10:20:00+05:30", "symbol": "ABC", "spot": 100, "strike": 100, "side": "PE", "oi": 100, "volume": 25, "iv": 19},
                ])
            news_root = root / "news"
            news_day = news_root / day
            news_day.mkdir(parents=True)
            event = {"source": "Example", "headline": "Company wins order", "published_at": "2026-09-29T10:00:00+05:30", "event_type": "order", "sentiment": "POSITIVE", "deduplication_key": "abc-key", "mapping": {"kind": "explicit_symbol", "symbol": "ABC"}}
            (news_day / "stock_events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
            prior_news = news_root / "2026-09-28"
            prior_news.mkdir()
            prior_event = {"source": "Example", "headline": "Prior sector context", "published_at": "2026-09-28T15:00:00+05:30", "deduplication_key": "prior-key", "mapping": {"kind": "explicit_source_sector", "sector": "Banking"}}
            (prior_news / "sector_events.jsonl").write_text(json.dumps(prior_event) + "\n", encoding="utf-8")

            result = build_why_moving(
                day=day,
                symbol="ABC",
                market={"sector": "Banking", "from_open_pct": 1.5, "direction": "UP"},
                technical={"move_5m_pct": 0.4, "rsi14_1m": 62, "points": 40},
                points=[{"ltp": 100}],
                reports_root=reports,
                options_root=options_root,
                news_root=news_root,
                now=now,
            )
            self.assertEqual(result["sector_alignment"], "ALIGNED")
            self.assertTrue(result["options"]["available"])
            self.assertEqual(result["options"]["pcr_oi"], 1.25)
            self.assertEqual(result["options"]["pcr_volume"], 1.25)
            self.assertEqual(len(result["news"]), 2)
            self.assertFalse(result["causality_claimed"])
            self.assertIn("HOLDING THESIS", {section["title"] for section in result["sections"]})

    def test_historical_day_does_not_reuse_a_different_day_market_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            (reports / "fno_market_watch_latest.json").write_text(json.dumps({
                "generated_at": "2026-09-29T10:00:00+05:30",
                "rows": [{"symbol": "ABC", "sector": "Banking", "from_open_pct": 2}],
            }), encoding="utf-8")
            result = build_why_moving(
                day="2026-09-28", symbol="ABC", market={}, technical={}, points=[],
                reports_root=reports, options_root=root / "options", news_root=root / "news",
                now=datetime(2026, 9, 29, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
            )
            self.assertEqual(result["sector"]["peer_count"], 0)
            self.assertEqual(result["confidence"], "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
