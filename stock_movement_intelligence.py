"""Explainable, local-only stock context for the Stock Analysis view."""
from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_time(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    result = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        result.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return result


def _sector_snapshot(reports_root: Path, day: str, symbol: str, sector: str) -> dict[str, Any]:
    report = _read_json(reports_root / "fno_market_watch_latest.json")
    report_time = _parse_time(report.get("generated_at"))
    rows = report.get("rows") if isinstance(report.get("rows"), list) and report_time and report_time.date().isoformat() == day else []
    peers = [row for row in rows if isinstance(row, dict) and sector and str(row.get("sector") or "") == sector]
    changes = [value for row in peers if (value := _number(row.get("from_open_pct"))) is not None]
    advances = sum(value > 0 for value in changes)
    declines = sum(value < 0 for value in changes)
    all_changes = [value for row in rows if isinstance(row, dict)
                   if (value := _number(row.get("from_open_pct"))) is not None]
    benchmark_rows = [row for row in rows if str(row.get("symbol") or "").upper() in {"NIFTY", "NIFTY50", "BANKNIFTY", "NIFTYBANK"}]
    benchmark_rows = [
        {"symbol": str(row.get("symbol")), "direction": row.get("direction"),
         "from_open_pct": _number(row.get("from_open_pct"))}
        for row in benchmark_rows
    ]
    return {
        "generated_at": report.get("generated_at", ""),
        "sector": sector or "UNCLASSIFIED",
        "peer_count": len(changes),
        "average_from_open_pct": round(sum(changes) / len(changes), 3) if changes else None,
        "advances": advances,
        "declines": declines,
        "benchmarks": benchmark_rows,
        "market_breadth": {
            "rows": len(all_changes),
            "advances": sum(value > 0 for value in all_changes),
            "declines": sum(value < 0 for value in all_changes),
            "average_from_open_pct": round(sum(all_changes) / len(all_changes), 3) if all_changes else None,
        },
    }


def _options_snapshot(options_root: Path, day: str, symbol: str) -> dict[str, Any]:
    path = options_root / day / "option_chain_rows.csv"
    try:
        stat = path.stat()
    except OSError:
        return {"available": False, "reason": "No local options-intelligence file for this date"}
    # The collector appends one symbol at a time; refresh at most once per minute
    # so the dashboard's five-second polling does not repeatedly parse a large CSV.
    refresh_bucket = int(stat.st_mtime // 60)
    return _options_snapshot_cached(str(path), refresh_bucket, symbol)


@lru_cache(maxsize=128)
def _options_snapshot_cached(path_text: str, refresh_bucket: int, symbol: str) -> dict[str, Any]:
    _ = refresh_bucket
    path = Path(path_text)
    rows = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [row for row in csv.DictReader(handle) if str(row.get("symbol") or "").upper() == symbol]
    except OSError:
        return {"available": False, "reason": "No local options-intelligence file for this date"}
    if not rows:
        return {"available": False, "reason": "No local option rows for this symbol/date"}
    latest = max(str(row.get("captured_at") or "") for row in rows)
    rows = [row for row in rows if str(row.get("captured_at") or "") == latest]
    ce = [row for row in rows if str(row.get("side") or "").upper() == "CE"]
    pe = [row for row in rows if str(row.get("side") or "").upper() == "PE"]
    ce_oi = sum(_number(row.get("oi")) or 0 for row in ce)
    pe_oi = sum(_number(row.get("oi")) or 0 for row in pe)
    ce_volume = sum(_number(row.get("volume")) or 0 for row in ce)
    pe_volume = sum(_number(row.get("volume")) or 0 for row in pe)
    ce_wall = max(ce, key=lambda row: _number(row.get("oi")) or 0, default={})
    pe_wall = max(pe, key=lambda row: _number(row.get("oi")) or 0, default={})
    spots = [_number(row.get("spot")) for row in rows]
    spot = next((value for value in spots if value is not None and value > 0), None)
    ivs = [_number(row.get("iv")) for row in rows]
    ivs = [value for value in ivs if value is not None]
    return {
        "available": True,
        "captured_at": latest,
        "row_count": len(rows),
        "pcr_oi": round(pe_oi / ce_oi, 3) if ce_oi else None,
        "pcr_volume": round(pe_volume / ce_volume, 3) if ce_volume else None,
        "call_oi_wall": _number(ce_wall.get("strike")) if ce_wall else None,
        "put_oi_wall": _number(pe_wall.get("strike")) if pe_wall else None,
        "atm_strike": min((_number(row.get("strike")) for row in rows if _number(row.get("strike")) is not None),
                           key=lambda strike: abs(strike - spot), default=None) if spot else None,
        "mean_iv": round(sum(ivs) / len(ivs), 2) if ivs else None,
        "source": "local Options Intelligence CSV",
    }


def _news_events(news_root: Path, day: str, symbol: str, sector: str, now: datetime) -> list[dict[str, Any]]:
    candidates = []
    try:
        report_day = date.fromisoformat(day)
    except ValueError:
        return []
    for offset in range(4):
        day_dir = news_root / (report_day - timedelta(days=offset)).isoformat()
        candidates.extend(_read_jsonl(day_dir / "stock_events.jsonl"))
        candidates.extend(_read_jsonl(day_dir / "sector_events.jsonl"))
    selected: dict[str, dict[str, Any]] = {}
    for item in candidates:
        mapping = item.get("mapping") if isinstance(item.get("mapping"), dict) else {}
        relevant = (
            (mapping.get("kind") == "explicit_symbol" and str(mapping.get("symbol") or "").upper() == symbol)
            or (mapping.get("symbol") and str(mapping.get("symbol") or "").upper() == symbol)
            or (mapping.get("sector") and str(mapping.get("sector") or "").casefold() == sector.casefold())
        )
        if not relevant:
            continue
        published = _parse_time(item.get("published_at") or item.get("captured_at"))
        if published is None:
            age_minutes = None
        else:
            age_minutes = max(0, int((now - published).total_seconds() / 60))
            if age_minutes > 72 * 60:
                continue
        key = str(item.get("deduplication_key") or item.get("url") or item.get("headline") or "")
        item_copy = dict(item)
        item_copy["news_age_minutes"] = age_minutes
        selected[key or str(len(selected))] = item_copy
    return sorted(selected.values(), key=lambda item: item.get("news_age_minutes") if item.get("news_age_minutes") is not None else 10**12)[:5]


def build_why_moving(
    *,
    day: str,
    symbol: str,
    market: dict[str, Any],
    technical: dict[str, Any],
    points: list[dict[str, Any]],
    candidate: dict[str, Any] | None = None,
    reports_root: Path | None = None,
    options_root: Path | None = None,
    news_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Combine local observations; never claim inferred causal attribution."""
    symbol = str(symbol or "").strip().upper()
    try:
        day = date.fromisoformat(str(day or "").strip()).isoformat()
    except ValueError:
        day = ""
    reports_root = reports_root or ROOT / "data" / "reports"
    options_root = options_root or ROOT / "data" / "options_intelligence"
    news_root = news_root or ROOT / "data" / "news_intelligence"
    now = now or datetime.now().astimezone()
    sector = str(market.get("sector") or "")
    sector_data = _sector_snapshot(reports_root, day, symbol, sector)
    options = dict(_options_snapshot(options_root, day, symbol))
    if options.get("available"):
        captured = _parse_time(options.get("captured_at"))
        options["age_minutes"] = max(0, int((now - captured).total_seconds() / 60)) if captured else None
    news = _news_events(news_root, day, symbol, sector, now)
    move = _number(market.get("from_open_pct"))
    direction = str(market.get("direction") or "").upper()
    average = sector_data.get("average_from_open_pct")
    technical_move = _number(technical.get("move_5m_pct"))

    if technical.get("points", 0) and technical_move is not None:
        technical_alignment = "UP" if technical_move > 0.05 else "DOWN" if technical_move < -0.05 else "FLAT"
    else:
        technical_alignment = "INSUFFICIENT_DATA"
    if move is not None and average is not None:
        sector_alignment = "ALIGNED" if (move >= 0) == (average >= 0) else "DIVERGENT"
    else:
        sector_alignment = "UNKNOWN"
    option_pcr = options.get("pcr_oi") if options.get("available") else None
    options_alignment = "PUT_OI_DOMINANT" if option_pcr is not None and option_pcr > 1.1 else (
        "CALL_OI_DOMINANT" if option_pcr is not None and option_pcr < 0.9 else
        "BALANCED_OR_UNKNOWN" if option_pcr is not None else "INSUFFICIENT_DATA"
    )

    observed = []
    if move is not None:
        observed.append(f"Report shows {move:+.2f}% from the 09:15 open ({direction or 'direction unavailable'}).")
    if technical_alignment != "INSUFFICIENT_DATA":
        observed.append(f"Local one-minute technical sample has {technical.get('points', 0)} points; five-minute move is {technical_move:+.2f}%.")
    if sector_data["peer_count"]:
        observed.append(f"{sector_data['peer_count']} same-sector report rows average {average:+.2f}% from open ({sector_data['advances']} up, {sector_data['declines']} down).")
    if options.get("available"):
        observed.append(f"Local option-chain capture at {options['captured_at']} contains {options['row_count']} rows; PCR by OI is {options['pcr_oi']}.")
    if news:
        observed.append(f"{len(news)} supplied news record(s) map to this symbol or its reported sector.")
    breadth = sector_data["market_breadth"]
    advances = breadth["advances"]
    declines = breadth["declines"]
    breadth_regime = "BROAD_ADVANCE" if breadth["rows"] and advances / breadth["rows"] >= 0.65 else (
        "BROAD_DECLINE" if breadth["rows"] and declines / breadth["rows"] >= 0.65 else
        "MIXED" if breadth["rows"] else "UNAVAILABLE"
    )
    market_context_items = [
        f"Market-watch snapshot {sector_data['generated_at'] or 'timestamp unavailable'}; breadth {breadth_regime} "
        f"({advances} advancing, {declines} declining of {breadth['rows']} rows)."
    ]
    market_context_items.extend(
        f"{item['symbol']}: {item['direction'] or 'direction unavailable'}, {item['from_open_pct']}% from open."
        for item in sector_data["benchmarks"]
    )
    if not sector_data["benchmarks"]:
        market_context_items.append("NIFTY/BANK NIFTY benchmark rows are not present in the local F&O snapshot.")

    candidate_context = candidate or {}
    candidate_keys = (
        "vwap", "vwap_distance_percent", "ema9_5m", "ema20_5m", "ema50_5m", "rsi14_5m",
        "adx14_5m", "relative_volume", "recent_relative_volume_15m", "pivot_state",
        "opening_range_breakout", "opening_direction_confirmed", "market_structure",
        "opening_structure",
    )
    technical_items = [f"{key}: {value}" for key, value in technical.items() if key != "points"]
    technical_items.extend(f"{key}: {candidate_context[key]}" for key in candidate_keys
                           if candidate_context.get(key) not in (None, "", "N/A"))
    technical_items.append(f"local sample points: {technical.get('points', 0)}")

    supporting = []
    contradicting = []
    possible = []
    if sector_alignment == "ALIGNED":
        supporting.append("Stock direction and same-sector average are aligned in the local market-watch snapshot.")
        possible.append("Sector-wide participation is a possible correlated context, not confirmed causality.")
    elif sector_alignment == "DIVERGENT":
        contradicting.append("Stock direction diverges from its same-sector average in the local snapshot.")
    if direction and technical_alignment in {"UP", "DOWN"}:
        if direction == technical_alignment:
            supporting.append("Short-term technical direction agrees with the market-watch direction.")
        else:
            contradicting.append("Short-term technical direction differs from the market-watch direction.")
    for item in news:
        title = str(item.get("headline") or "")
        if title:
            possible.append(f"Reported item from {item.get('source') or 'unknown source'}: {title}")
            supporting.append(f"News classification evidence: {', '.join(item.get('sentiment_evidence') or []) or 'no directional keyword evidence'}.")
    if options.get("available"):
        supporting.append(f"Options positioning is descriptively {options_alignment.lower().replace('_', ' ')}; this is not a directional forecast.")

    coverage = sum(bool(value) for value in (market, technical.get("points"), sector_data["peer_count"], options.get("available"), news))
    confidence = "MODERATE" if coverage >= 4 and len(supporting) >= 2 else "LOW" if coverage else "INSUFFICIENT_DATA"
    age_values = [item["news_age_minutes"] for item in news if item.get("news_age_minutes") is not None]
    newest_news_age = min(age_values) if age_values else None

    sections = [
        {"title": "MARKET CONTEXT", "items": market_context_items + (observed[:1] or ["No current market-watch observation for this symbol."])},
        {"title": "TECHNICAL CONTEXT", "items": technical_items or ["No local technical sample available."]},
        {"title": "SECTOR CONTEXT", "items": [f"{sector or 'Sector unavailable'}: {sector_data['peer_count']} peers; average {average if average is not None else 'unavailable'}% from open; {sector_data['advances']} advancing, {sector_data['declines']} declining."]},
        {"title": "OPTIONS INTELLIGENCE", "items": ([f"Capture {options['captured_at']} ({options.get('age_minutes')} min old); rows {options['row_count']}; PCR OI {options['pcr_oi']}; PCR volume {options['pcr_volume']}; call wall {options['call_oi_wall']}; put wall {options['put_oi_wall']}; mean IV {options['mean_iv']}."] if options.get("available") else [options.get("reason", "No local options evidence.")])},
        {"title": "NEWS / CATALYST", "items": ([f"{item.get('source')}: {item.get('headline')} (reported; age {item.get('news_age_minutes')} min; {item.get('event_type')}; {item.get('sentiment')})." for item in news] if news else ["No supplied, mapped news records are available for the recent window."])},
        {"title": "WHY THIS STOCK IS MOVING", "items": possible or ["Available observations do not identify a specific possible driver."]},
        {"title": "HOLDING THESIS", "items": ["No holding, entry thesis, or position data was supplied to this read-only analysis."]},
        {"title": "INVALIDATION / RISK", "items": contradicting or ["No contradicting evidence was found in the available local sources; this does not remove market risk."]},
    ]
    return {
        "observed_facts": observed,
        "possible_drivers": possible,
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "confidence": confidence,
        "news_age": {"newest_minutes": newest_news_age, "window_hours": 72},
        "technical_alignment": technical_alignment,
        "sector_alignment": sector_alignment,
        "options_alignment": options_alignment,
        "options": options,
        "news": news,
        "sector": sector_data,
        "sections": sections,
        "read_only": True,
        "causality_claimed": False,
    }


__all__ = ["build_why_moving"]
