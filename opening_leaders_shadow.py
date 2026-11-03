"""Read-only opening-move rankings from the scanner's existing F&O report.

This is an information-only dashboard helper. It does not fetch market data,
score a trade, or feed any scanner, strategy, or order path.
"""

from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def build_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Return separate gainers/decliners, ranked only by reported move from open."""
    rows: list[dict[str, Any]] = []
    for source in report.get("rows") or []:
        if not isinstance(source, dict):
            continue
        symbol = str(source.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        move = _number(source.get("from_open_pct"))
        if move is None:
            continue
        rows.append({
            "symbol": symbol,
            "sector": str(source.get("sector") or "UNCLASSIFIED"),
            "open_0915": _number(source.get("open_0915")),
            "ltp": _number(source.get("ltp")),
            "previous_close": _number(source.get("previous_close")),
            "gap_pct": _number(source.get("gap_pct")),
            "from_open_pct": move,
            "from_prev_close_pct": _number(source.get("from_prev_close_pct")),
            "day_high": _number(source.get("day_high")),
            "day_low": _number(source.get("day_low")),
            "range_position_pct": _number(source.get("range_position_pct")),
        })

    gainers = sorted((r for r in rows if r["from_open_pct"] > 0), key=lambda r: (-r["from_open_pct"], r["symbol"]))[:10]
    decliners = sorted((r for r in rows if r["from_open_pct"] < 0), key=lambda r: (r["from_open_pct"], r["symbol"]))[:10]
    for group in (gainers, decliners):
        for rank, row in enumerate(group, 1):
            row["rank"] = rank

    return {
        "mode": "SHADOW_INFORMATION_ONLY",
        "source": "existing F&O market-watch scanner report",
        "source_file": "data/reports/fno_market_watch_latest.json",
        "generated_at": str(report.get("generated_at") or ""),
        "age_seconds": _number(report.get("age_seconds")),
        "stale": bool(report.get("stale", True)),
        "stale_reason": str(report.get("stale_reason") or ""),
        "count": len(rows),
        "gainers": gainers,
        "decliners": decliners,
        "limitations": [
            "Ranked by reported change from the 09:15 open only; no composite score is invented.",
            "The source report does not provide first-minute candle volume, relative volume, or VWAP confirmation.",
            "This view is informational and is not a trade recommendation or execution signal.",
        ],
    }

