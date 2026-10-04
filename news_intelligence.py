from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
NEWS_DIR = ROOT / "data" / "news_intelligence"
EVENTS_PATH = NEWS_DIR / "events.jsonl"

IMPACT_ORDER = {"VERY HIGH": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbols(event: dict[str, Any]) -> set[str]:
    values = event.get("symbols") or event.get("symbol") or []
    if isinstance(values, str):
        values = re.split(r"[,;|\s]+", values)
    return {str(v).strip().upper() for v in values if str(v).strip()}


def _normalise(event: dict[str, Any]) -> dict[str, Any]:
    item = dict(event)
    item["symbol"] = _text(item.get("symbol")).upper()
    item["symbols"] = sorted(_symbols(item))
    item["title"] = _text(item.get("title") or item.get("headline"))
    item["summary"] = _text(item.get("summary") or item.get("description"))
    item["direction"] = _text(item.get("direction") or "NEUTRAL").upper()
    item["impact"] = _text(item.get("impact") or "UNKNOWN").upper()
    item["source_type"] = _text(item.get("source_type") or item.get("source") or "UNKNOWN")
    item["source_url"] = _text(item.get("source_url") or item.get("url"))
    item["published_at"] = _text(item.get("published_at") or item.get("timestamp"))
    try:
        item["confidence"] = max(0.0, min(1.0, float(item.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        item["confidence"] = 0.0
    return item


def load_events(path: Path = EVENTS_PATH) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(_normalise(value))
    except OSError:
        return []
    return events


def _relevant(event: dict[str, Any], symbol: str) -> bool:
    symbol = symbol.strip().upper()
    if not symbol:
        return False
    if symbol in _symbols(event):
        return True
    haystack = " ".join(
        [_text(event.get("title")), _text(event.get("summary")), _text(event.get("company"))]
    ).upper()
    return re.search(rf"\b{re.escape(symbol)}\b", haystack) is not None


def news_context(
    symbol: str,
    *,
    as_of: datetime | None = None,
    max_age_hours: float = 72.0,
    limit: int = 8,
) -> dict[str, Any]:
    """Build observational news context from timestamped local events.

    Historical callers should pass an explicit as_of timestamp so future news
    cannot leak into a past decision.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"ok": False, "data_status": "UNAVAILABLE", "symbol": "", "events": [],
                "summary": "Symbol is required.", "read_only": True}

    reference = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    max_age = max(0.0, float(max_age_hours))
    matched: list[dict[str, Any]] = []
    for event in load_events():
        if not _relevant(event, symbol):
            continue
        published = _parse_time(event.get("published_at"))
        if published is None or published > reference:
            continue
        age_hours = (reference - published).total_seconds() / 3600.0
        if age_hours < 0 or age_hours > max_age:
            continue
        item = dict(event)
        item["age_hours"] = round(age_hours, 2)
        matched.append(item)

    matched.sort(
        key=lambda x: (
            IMPACT_ORDER.get(_text(x.get("impact")).upper(), 0),
            -float(x.get("age_hours") or 0.0),
            float(x.get("confidence") or 0.0),
        ),
        reverse=True,
    )
    matched = matched[: max(1, int(limit))]

    counts = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0, "MIXED": 0}
    for event in matched:
        direction = _text(event.get("direction")).upper()
        if direction in counts:
            counts[direction] += 1

    if not matched:
        summary = "No timestamped local news found inside the configured lookback window."
        status = "NO_MATCH"
    else:
        summary = (
            f"{len(matched)} relevant news event(s); "
            f"bullish={counts['BULLISH']}, bearish={counts['BEARISH']}, "
            f"neutral={counts['NEUTRAL']}, mixed={counts['MIXED']}."
        )
        status = "AVAILABLE"

    return {
        "ok": True, "data_status": status, "symbol": symbol,
        "lookback_hours": max_age, "events": matched,
        "direction_counts": counts, "summary": summary,
        "read_only": True, "trading_engine_untouched": True,
    }


def write_jsonl(events: list[dict[str, Any]], path: Path = EVENTS_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            item = _normalise(event)
            if not item.get("title") or not item.get("published_at"):
                continue
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


__all__ = ["EVENTS_PATH", "load_events", "news_context", "write_jsonl"]
