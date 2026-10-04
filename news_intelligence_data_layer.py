"""Offline, read-only normalization and storage for supplied news records.

This module does not fetch news and does not call broker or trading APIs.
Classifications are deterministic keyword observations; they are not claims
that a reported event caused a market move.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
DEFAULT_ROOT = ROOT / "data" / "news_intelligence"

# Each rule retains the exact matched terms as reviewable classification evidence.
RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("COMPANY", "earnings", ("quarterly results", "earnings", "net profit", "revenue")),
    ("COMPANY", "guidance", ("guidance", "outlook", "forecast")),
    ("COMPANY", "order", ("order win", "new order", "contract win", "work order")),
    ("COMPANY", "acquisition", ("acquisition", "acquires", "merger", "takeover")),
    ("COMPANY", "management", ("ceo resigns", "appointed ceo", "managing director", "board resigns")),
    ("COMPANY", "fundraising", ("fundraising", "preferential issue", "qualified institutional placement", "qip")),
    ("COMPANY", "litigation", ("court order", "lawsuit", "legal notice", "litigation")),
    ("COMPANY", "rating", ("credit rating", "rating upgrade", "rating downgrade")),
    ("COMPANY", "promoter_activity", ("promoter pledge", "promoter stake", "promoter sold", "promoter bought")),
    ("COMPANY", "corporate_action", ("stock split", "bonus issue", "dividend", "buyback")),
    ("REGULATORY", "sebi", ("sebi", "securities and exchange board")),
    ("REGULATORY", "rbi", ("reserve bank of india", "rbi policy", "rbi")),
    ("REGULATORY", "irdai", ("irdai", "insurance regulator")),
    ("REGULATORY", "trai", ("trai", "telecom regulator")),
    ("REGULATORY", "government_policy", ("government policy", "cabinet approves", "ministry of", "policy proposal")),
    ("REGULATORY", "taxation", ("tax rate", "taxation", "gst council", "customs duty")),
    ("MACRO", "crude", ("crude oil", "brent", "wti")),
    ("MACRO", "currency", ("rupee", "us dollar", "currency market", "forex")),
    ("MACRO", "interest_rates", ("interest rate", "rate cut", "rate hike", "bond yield")),
    ("MACRO", "inflation", ("inflation", "consumer prices", "cpi")),
    ("MACRO", "central_banks", ("federal reserve", "central bank", "monetary policy")),
    ("MACRO", "geopolitical", ("geopolitical", "sanctions", "ceasefire", "trade war")),
    ("MACRO", "commodities", ("gold prices", "copper prices", "commodity prices")),
    ("MACRO", "global_markets", ("global markets", "wall street", "asian markets")),
    ("SECTOR", "banking", ("banking sector", "private banks", "public sector banks")),
    ("SECTOR", "insurance", ("insurance sector", "insurers")),
    ("SECTOR", "it", ("information technology sector", "it services sector")),
    ("SECTOR", "auto", ("automobile sector", "auto sector", "vehicle sales")),
    ("SECTOR", "pharma", ("pharmaceutical sector", "drug makers", "pharma sector")),
    ("SECTOR", "energy", ("energy sector", "power sector", "renewable energy")),
    ("SECTOR", "metals", ("metal sector", "steel sector", "aluminium sector")),
    ("SECTOR", "real_estate", ("real estate sector", "property market")),
    ("SECTOR", "telecom", ("telecom sector", "telecommunications sector")),
)
POSITIVE_TERMS = ("beats estimates", "profit rises", "upgrade", "wins order", "record revenue", "approval granted")
NEGATIVE_TERMS = ("misses estimates", "profit falls", "downgrade", "order cancelled", "investigation", "approval denied")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,;]", value)
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _evidence_classification(headline: str, summary: str) -> list[dict[str, Any]]:
    haystack = f"{headline} {summary}".casefold()
    found = []
    for category, event_type, terms in RULES:
        matches = [term for term in terms if term.casefold() in haystack]
        if matches:
            found.append({
                "category": category,
                "event_type": event_type,
                "matched_terms": matches,
                "evidence": f"Matched in supplied headline/summary: {', '.join(matches)}",
            })
    return found


def _sentiment(headline: str, summary: str) -> tuple[str, str, int, list[str]]:
    haystack = f"{headline} {summary}".casefold()
    positive = [term for term in POSITIVE_TERMS if term in haystack]
    negative = [term for term in NEGATIVE_TERMS if term in haystack]
    score = len(positive) - len(negative)
    direction = "POSITIVE" if score > 0 else "NEGATIVE" if score < 0 else "NEUTRAL_OR_UNKNOWN"
    strength = "HIGH" if abs(score) >= 2 else "MEDIUM" if score else "LOW_OR_UNKNOWN"
    return direction, strength, score, positive + negative


def normalize_event(
    record: dict[str, Any],
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Normalize one source record without creating missing factual claims."""
    if not isinstance(record, dict):
        raise ValueError("news record must be an object")
    headline = _text(record.get("headline"))
    source = _text(record.get("source"))
    if not headline or not source:
        raise ValueError("news record requires non-empty source and headline")

    captured = captured_at or datetime.now().astimezone().isoformat()
    published = _text(record.get("published_at"))
    summary = _text(record.get("summary"))
    classifications = _evidence_classification(headline, summary)
    sentiment, strength, score, sentiment_terms = _sentiment(headline, summary)
    symbols = [item.upper() for item in _string_list(record.get("symbols"))]
    sectors = _string_list(record.get("sectors"))
    url = _text(record.get("url") or record.get("reference"))
    dedupe_material = url.casefold() if url else f"{source.casefold()}|{' '.join(headline.casefold().split())}"
    dedupe_key = hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest()
    categories = {item["category"] for item in classifications}
    primary = classifications[0]["event_type"] if classifications else "unclassified"
    # An explicit source-provided event type is preserved only when no rule matched.
    if not classifications and _text(record.get("event_type")):
        primary = _text(record.get("event_type"))

    entities = _string_list(record.get("entities"))
    entities.extend(item for item in symbols if item not in entities)
    event = {
        "captured_at": captured,
        "published_at": published,
        "source": source,
        "headline": headline,
        "summary": summary,
        "url": url,
        "reference": _text(record.get("reference")) or url,
        "event_type": primary,
        "classifications": classifications,
        "entities": entities,
        "symbols": symbols,
        "sectors": sectors,
        "geography": _text(record.get("geography")),
        "sentiment": sentiment,
        "impact_direction": "POSSIBLE_UP" if sentiment == "POSITIVE" else "POSSIBLE_DOWN" if sentiment == "NEGATIVE" else "UNKNOWN",
        "impact_strength": strength,
        "confidence": round(min(0.85, 0.35 + 0.1 * len(classifications) + 0.05 * bool(sentiment_terms)), 2),
        "sentiment_evidence": sentiment_terms,
        "regulatory": "REGULATORY" in categories,
        "macro": "MACRO" in categories,
        "company_specific": "COMPANY" in categories or bool(symbols),
        "deduplication_key": dedupe_key,
        "classification_basis": "deterministic keyword matches in supplied headline/summary",
        "causality_claimed": False,
    }
    # Store caller-supplied observations verbatim for later historical analysis.
    observations = record.get("observations")
    if isinstance(observations, dict):
        event["observations"] = observations
        event["historical_observations"] = {
            "price_reaction": observations.get("price_reaction"),
            "technical_state": observations.get("technical_state"),
            "option_state": observations.get("option_state"),
            "subsequent_movement": observations.get("subsequent_movement"),
        }
    return event


def symbol_sector_map(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Build local symbol-to-sector links from a supplied market-watch snapshot."""
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol, sector = _text(row.get("symbol")).upper(), _text(row.get("sector"))
        if symbol and sector and sector.upper() != "UNCLASSIFIED":
            result[symbol] = sector
    return result


def map_event(event: dict[str, Any], sectors_by_symbol: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Create explicit many-to-many stock/sector edges with provenance."""
    stock_events = []
    sector_events = []
    for symbol in event.get("symbols", []):
        stock_events.append({**event, "mapping": {"kind": "explicit_symbol", "symbol": symbol}})
        sector = sectors_by_symbol.get(symbol)
        if sector:
            sector_events.append({**event, "mapping": {"kind": "market_watch_symbol_sector", "symbol": symbol, "sector": sector}})
    for sector in event.get("sectors", []):
        sector_events.append({**event, "mapping": {"kind": "explicit_source_sector", "sector": sector}})
    return stock_events, sector_events


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return len(records)


def _read_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.is_file():
        return keys
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
                key = _text(item.get("deduplication_key")) if isinstance(item, dict) else ""
                if key:
                    keys.add(key)
            except json.JSONDecodeError:
                continue
    return keys


def _manifest(day_dir: Path, ingest_counts: Counter[str]) -> dict[str, Any]:
    files = {}
    for name in ("news_events.jsonl", "stock_events.jsonl", "sector_events.jsonl"):
        path = day_dir / name
        if path.exists():
            files[name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    total_lines = {}
    for name in ("news_events.jsonl", "stock_events.jsonl", "sector_events.jsonl"):
        path = day_dir / name
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                total_lines[name] = sum(1 for line in handle if line.strip())
    return {
        "service": "APlus News Intelligence Data Layer",
        "schema_version": 1,
        "read_only": True,
        "updated_at": datetime.now().astimezone().isoformat(),
        "event_count": total_lines.get("news_events.jsonl", 0),
        "stock_mapping_count": total_lines.get("stock_events.jsonl", 0),
        "sector_mapping_count": total_lines.get("sector_events.jsonl", 0),
        "last_ingest": dict(ingest_counts),
        "files": files,
        "causality_claimed": False,
    }


def ingest_records(
    records: Iterable[dict[str, Any]],
    *,
    storage_root: Path = DEFAULT_ROOT,
    sectors_by_symbol: dict[str, str] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Append non-duplicate source records to date-partitioned local JSONL."""
    captured = captured_at or datetime.now().astimezone().isoformat()
    captured_dt = _parse_date(captured) or datetime.now().astimezone()
    root = Path(storage_root)
    by_day: dict[str, list[dict[str, Any]]] = {}
    for raw in records:
        event = normalize_event(raw, captured_at=captured)
        published_dt = _parse_date(event["published_at"])
        day = (published_dt or captured_dt).date().isoformat()
        by_day.setdefault(day, []).append(event)

    totals = Counter()
    day_summaries = {}
    sector_map = sectors_by_symbol or {}
    for day, events in by_day.items():
        day_dir = root / day
        news_path = day_dir / "news_events.jsonl"
        known = _read_keys(news_path)
        unique = []
        for event in events:
            key = event["deduplication_key"]
            if key not in known:
                unique.append(event)
                known.add(key)
        stocks: list[dict[str, Any]] = []
        sectors: list[dict[str, Any]] = []
        for event in unique:
            stock_rows, sector_rows = map_event(event, sector_map)
            stocks.extend(stock_rows)
            sectors.extend(sector_rows)
        event_count = _append_jsonl(news_path, unique)
        stock_count = _append_jsonl(day_dir / "stock_events.jsonl", stocks)
        sector_count = _append_jsonl(day_dir / "sector_events.jsonl", sectors)
        counts = Counter({"events": event_count, "stock_mappings": stock_count, "sector_mappings": sector_count})
        manifest_path = day_dir / "intelligence_manifest.json"
        payload = _manifest(day_dir, counts)
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(manifest_path)
        totals.update(counts)
        day_summaries[day] = dict(counts)

    return {"accepted": sum(len(items) for items in by_day.values()), "written": totals["events"],
            "stock_mappings": totals["stock_mappings"], "sector_mappings": totals["sector_mappings"],
            "days": day_summaries, "read_only": True, "causality_claimed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize supplied news JSONL into local read-only intelligence files.")
    parser.add_argument("--input", required=True, type=Path, help="JSONL records with source and headline fields")
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--market-watch", type=Path, default=ROOT / "data" / "reports" / "fno_market_watch_latest.json")
    args = parser.parse_args()
    records = []
    with args.input.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                parser.error(f"invalid JSON on line {number}: {exc.msg}")
            if not isinstance(record, dict):
                parser.error(f"line {number} must contain a JSON object")
            records.append(record)
    rows: list[dict[str, Any]] = []
    try:
        payload = json.loads(args.market_watch.read_text(encoding="utf-8"))
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
    except (OSError, json.JSONDecodeError):
        pass
    result = ingest_records(records, storage_root=args.storage_root, sectors_by_symbol=symbol_sector_map(rows))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
