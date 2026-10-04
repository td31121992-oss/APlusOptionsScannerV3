from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import news_intelligence_data_layer as news
import sebi_rss_adapter as adapter


RSS_FIXTURE = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'><channel><title>SEBI RSS</title>
  <item>
    <title>SEBI issues market circular</title>
    <link>https://www.sebi.gov.in/circular/1</link>
    <guid>sebi-item-1</guid>
    <pubDate>Tue, 29 Sep 2026 10:00:00 +0530</pubDate>
    <description>&lt;p&gt;A &lt;b&gt;market&lt;/b&gt; circular.&lt;/p&gt;</description>
  </item>
  <item>
    <title>Duplicate entry</title>
    <link>https://www.sebi.gov.in/circular/1</link>
    <pubDate>Tue, 29 Sep 2026 10:00:00 +0530</pubDate>
  </item>
  <item>
    <title>Missing provider timestamp</title>
    <link>https://www.sebi.gov.in/circular/2</link>
  </item>
  <item>
    <title>Timezone-less timestamp</title>
    <link>https://www.sebi.gov.in/circular/3</link>
    <pubDate>2026-09-29T10:05:00</pubDate>
  </item>
  <item>
    <link>https://www.sebi.gov.in/circular/4</link>
    <pubDate>Tue, 29 Sep 2026 10:00:00 +0530</pubDate>
  </item>
</channel></rss>"""


class _Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class SebiRssAdapterTests(unittest.TestCase):
    def test_parse_preserves_attribution_timestamp_and_skips_bad_or_duplicate_items(self) -> None:
        result = adapter.parse_feed(RSS_FIXTURE)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.skipped, 4)
        record = result.records[0]
        self.assertEqual(record["source"], adapter.SOURCE_NAME)
        self.assertEqual(record["published_at"], "2026-09-29T10:00:00+05:30")
        self.assertEqual(record["url"], "https://www.sebi.gov.in/circular/1")
        self.assertEqual(record["reference"], "sebi-item-1")
        self.assertEqual(record["summary"], "A market circular.")

    def test_parsed_record_flows_through_existing_jsonl_schema(self) -> None:
        record = adapter.parse_feed(RSS_FIXTURE).records[0]
        with tempfile.TemporaryDirectory() as tmp:
            result = news.ingest_records([record], storage_root=Path(tmp))
            event_path = Path(tmp) / "2026-09-29" / "news_events.jsonl"
            event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(result["written"], 1)
        self.assertEqual(event["source"], adapter.SOURCE_NAME)
        self.assertEqual(event["published_at"], "2026-09-29T10:00:00+05:30")
        self.assertEqual(event["url"], "https://www.sebi.gov.in/circular/1")
        self.assertFalse(event["causality_claimed"])

    def test_fetch_uses_fixed_feed_once_and_reports_timeout_and_transport_failures_safely(self) -> None:
        calls = []

        def opener(request, *, timeout):
            calls.append((request.full_url, timeout))
            return _Response(RSS_FIXTURE)

        self.assertEqual(adapter.fetch_feed(opener), RSS_FIXTURE)
        self.assertEqual(calls, [(adapter.FEED_URL, adapter.REQUEST_TIMEOUT_SECONDS)])

        def failing_opener(_request, *, timeout):
            raise urllib.error.URLError("proxy credential=must-not-appear")

        with self.assertRaises(adapter.FeedUnavailable) as error:
            adapter.fetch_feed(failing_opener)
        self.assertIn("URLError", str(error.exception))
        self.assertNotIn("must-not-appear", str(error.exception))

        def timing_out_opener(_request, *, timeout):
            raise TimeoutError("provider timed out")

        with self.assertRaises(adapter.FeedUnavailable) as timeout_error:
            adapter.fetch_feed(timing_out_opener)
        self.assertIn("TimeoutError", str(timeout_error.exception))
        self.assertNotIn("provider", str(timeout_error.exception))

    def test_import_and_default_cli_are_network_disabled(self) -> None:
        with patch.object(adapter, "fetch_feed", side_effect=AssertionError("unexpected fetch")) as fetch:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    adapter.main([])
        self.assertEqual(result.exception.code, 2)
        fetch.assert_not_called()

    def test_malformed_or_unsafe_xml_fails_without_partial_records(self) -> None:
        for payload in (b"<rss>", b"<!DOCTYPE rss [<!ENTITY x 'bad'>]><rss/>", b"<html/>"):
            with self.subTest(payload=payload[:20]):
                with self.assertRaises(adapter.FeedUnavailable):
                    adapter.parse_feed(payload)


if __name__ == "__main__":
    unittest.main()
