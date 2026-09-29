from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import news_intelligence_data_layer as news


class NewsIntelligenceTests(unittest.TestCase):
    def test_classification_preserves_source_and_matched_evidence(self) -> None:
        event = news.normalize_event({
            "source": "Example Exchange Filing",
            "headline": "RELIANCE wins order; quarterly results show company beats estimates",
            "summary": "The company reported a new order.",
            "symbols": ["reliance"],
            "url": "https://example.invalid/story/1",
        }, captured_at="2026-09-29T10:00:00+05:30")
        self.assertEqual(event["source"], "Example Exchange Filing")
        self.assertTrue(event["company_specific"])
        self.assertFalse(event["causality_claimed"])
        self.assertIn("order", {item["event_type"] for item in event["classifications"]})
        self.assertIn("earnings", {item["event_type"] for item in event["classifications"]})
        self.assertIn("beats estimates", event["sentiment_evidence"])

    def test_requires_source_and_headline(self) -> None:
        with self.assertRaises(ValueError):
            news.normalize_event({"headline": "No source provided"})

    def test_maps_only_explicit_symbols_and_source_sectors(self) -> None:
        event = news.normalize_event({
            "source": "Example", "headline": "SEBI issues new guidance",
            "symbols": ["ABC"], "sectors": ["Financial Services"],
        }, captured_at="2026-09-29T10:00:00+05:30")
        stocks, sectors = news.map_event(event, {"ABC": "Banking", "XYZ": "IT"})
        self.assertEqual([row["mapping"]["symbol"] for row in stocks], ["ABC"])
        self.assertEqual({row["mapping"]["sector"] for row in sectors}, {"Banking", "Financial Services"})
        self.assertNotIn("XYZ", {row["mapping"].get("symbol") for row in sectors})

    def test_daily_storage_deduplicates_and_writes_manifest_hashes(self) -> None:
        record = {
            "source": "Example", "headline": "Banking sector outlook",
            "published_at": "2026-09-29T10:00:00+05:30", "symbols": ["ABC"],
            "observations": {
                "price_reaction": {"from_open_pct": 1.2},
                "technical_state": {"rsi14": 58},
                "option_state": {"pcr_oi": 1.1},
                "subsequent_movement": {"return_30m_pct": 0.4},
            },
        }
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            root = Path(tmp)
            first = news.ingest_records([record], storage_root=root, sectors_by_symbol={"ABC": "Banking"},
                                        captured_at="2026-09-29T10:01:00+05:30")
            second = news.ingest_records([record], storage_root=root, sectors_by_symbol={"ABC": "Banking"},
                                         captured_at="2026-09-29T10:02:00+05:30")
            day = root / "2026-09-29"
            events = [json.loads(line) for line in (day / "news_events.jsonl").read_text(encoding="utf-8").splitlines()]
            stock_rows = (day / "stock_events.jsonl").read_text(encoding="utf-8").splitlines()
            sector_rows = (day / "sector_events.jsonl").read_text(encoding="utf-8").splitlines()
            manifest = json.loads((day / "intelligence_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(first["written"], 1)
            self.assertEqual(second["written"], 0)
            self.assertEqual(len(events), 1)
            self.assertEqual(len(stock_rows), 1)
            self.assertEqual(len(sector_rows), 1)
            self.assertIn("price_reaction", events[0]["observations"])
            self.assertEqual(events[0]["historical_observations"]["option_state"]["pcr_oi"], 1.1)
            self.assertEqual(manifest["event_count"], 1)
            expected = hashlib.sha256((day / "news_events.jsonl").read_bytes()).hexdigest()
            self.assertEqual(manifest["files"]["news_events.jsonl"]["sha256"], expected)

    def test_unknown_news_is_not_given_an_invented_classification(self) -> None:
        event = news.normalize_event({"source": "Example", "headline": "A supplied headline"},
                                     captured_at="2026-09-29T10:00:00+05:30")
        self.assertEqual(event["event_type"], "unclassified")
        self.assertEqual(event["impact_direction"], "UNKNOWN")
        self.assertEqual(event["sentiment"], "NEUTRAL_OR_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
