"""Opt-in reader for SEBI's public RSS announcements feed.

This module performs no work when imported. Run it explicitly with ``--fetch``
to make one read-only HTTP request and ingest RSS items into the local News
Intelligence store. It does not import broker or trading code.
"""
from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from news_intelligence_data_layer import DEFAULT_ROOT, ingest_records


FEED_URL = "https://www.sebi.gov.in/sebirss.xml"
SOURCE_NAME = "Securities and Exchange Board of India (SEBI) RSS"
REQUEST_TIMEOUT_SECONDS = 15
MAX_FEED_BYTES = 3 * 1024 * 1024


class FeedUnavailable(RuntimeError):
    """A safe, credential-free summary of a source retrieval/parse failure."""


@dataclass(frozen=True)
class FeedParseResult:
    records: list[dict[str, str]]
    skipped: int


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html.unescape(value))
        extractor.close()
    except Exception:
        return " ".join(value.split())[:4000]
    return " ".join(" ".join(extractor.parts).split())[:4000]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _child_text(item: ET.Element, *names: str) -> str:
    expected = {name.casefold() for name in names}
    for child in item:
        if _local_name(child.tag) in expected:
            return "".join(child.itertext()).strip()
    return ""


def _parse_published(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def parse_feed(payload: bytes) -> FeedParseResult:
    """Parse RSS items into existing News Intelligence source records.

    Entries without a title or an explicit timezone-aware publication time are
    skipped. The provider timestamp is represented as ISO-8601 with its offset;
    no publication time is synthesized from the fetch/capture time.
    """
    if not payload or len(payload) > MAX_FEED_BYTES:
        raise FeedUnavailable("SEBI RSS response is empty or exceeds the size limit")
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", payload, flags=re.IGNORECASE):
        raise FeedUnavailable("SEBI RSS response contains a prohibited XML declaration")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise FeedUnavailable(f"SEBI RSS XML is malformed ({type(exc).__name__})") from None

    if _local_name(root.tag) == "rss":
        items = [element for element in root.iter() if _local_name(element.tag) == "item"]
    elif _local_name(root.tag) == "feed":
        items = [element for element in root if _local_name(element.tag) == "entry"]
    else:
        raise FeedUnavailable("SEBI response is not an RSS or Atom feed")

    records: list[dict[str, str]] = []
    seen: set[str] = set()
    skipped = 0
    for item in items:
        title = _plain_text(_child_text(item, "title"))
        published_raw = _child_text(item, "pubDate", "published", "updated", "date")
        published = _parse_published(published_raw)
        link = _child_text(item, "link")
        if not link:
            link = next((node.attrib.get("href", "").strip() for node in item
                         if _local_name(node.tag) == "link" and node.attrib.get("href")), "")
        guid = _child_text(item, "guid", "id")
        summary = _plain_text(_child_text(item, "description", "summary", "content"))

        if not title or published is None:
            skipped += 1
            continue
        identity = (link or guid or f"{title.casefold()}|{published.isoformat()}").casefold()
        if identity in seen:
            skipped += 1
            continue
        seen.add(identity)
        record = {
            "source": SOURCE_NAME,
            "headline": title,
            "published_at": published.isoformat(),
        }
        if summary:
            record["summary"] = summary
        if link:
            record["url"] = link
        if guid and guid != link:
            record["reference"] = guid
        records.append(record)
    return FeedParseResult(records=records, skipped=skipped)


def fetch_feed(
    opener: Callable[..., object] = urllib.request.urlopen,
    *,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> bytes:
    """Fetch the fixed public feed once; callers may inject an opener in tests."""
    request = urllib.request.Request(
        FEED_URL,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9",
            "User-Agent": "APlus-News-Intelligence/1.0 (opt-in RSS reader)",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:  # type: ignore[attr-defined]
            status = getattr(response, "status", 200)
            if status != 200:
                raise FeedUnavailable(f"SEBI RSS returned HTTP {status}")
            payload = response.read(MAX_FEED_BYTES + 1)
    except FeedUnavailable:
        raise
    except urllib.error.HTTPError as exc:
        raise FeedUnavailable(f"SEBI RSS returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Do not print response bodies, request headers, proxy credentials, or URLs
        # from lower-level exception text.
        raise FeedUnavailable(f"SEBI RSS retrieval failed ({type(exc).__name__})") from None
    if len(payload) > MAX_FEED_BYTES:
        raise FeedUnavailable("SEBI RSS response exceeds the size limit")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in local SEBI RSS ingestion")
    parser.add_argument("--fetch", action="store_true", help="make one request to the SEBI RSS feed")
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    if not args.fetch:
        parser.error("feed retrieval is disabled unless --fetch is supplied")
    try:
        parsed = parse_feed(fetch_feed())
        result = ingest_records(parsed.records, storage_root=args.storage_root)
    except FeedUnavailable as exc:
        print(json.dumps({"status": "SOURCE_UNAVAILABLE", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({
        "status": "OK",
        "source": SOURCE_NAME,
        "feed_url": FEED_URL,
        "items_parsed": len(parsed.records),
        "items_skipped": parsed.skipped,
        "ingestion": result,
        "read_only": True,
        "causality_claimed": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
