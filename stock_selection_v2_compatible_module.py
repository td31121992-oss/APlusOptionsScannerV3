from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class V2GateConfig:
    top_n_per_side: int = 5
    minimum_session_move_pct: float = 0.50
    maximum_opposing_5m_pct: float = 0.06
    minimum_recent_10m_pct: float = 0.08
    minimum_recent_15m_pct: float = 0.12
    minimum_trend_retention_pct: float = 55.0
    minimum_participation: float = 1.20


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError, OverflowError):
        return default


def rank_raw_movers(
    *,
    universe: Sequence[Any],
    quote_map: Mapping[str, Any],
    top_n: int = 5,
) -> dict[str, Any]:
    segment = quote_map.get("NSE_EQ", {})
    if not isinstance(segment, Mapping):
        segment = {}

    rows: list[dict[str, Any]] = []
    for item in universe:
        sid = str(getattr(item, "security_id", "") or "")
        symbol = str(getattr(item, "symbol", "") or "").strip().upper()
        if not sid or not symbol:
            continue
        raw = segment.get(sid)
        if raw is None:
            try:
                raw = segment.get(int(sid))
            except (TypeError, ValueError):
                raw = None
        if not isinstance(raw, Mapping):
            continue
        ohlc = raw.get("ohlc")
        if not isinstance(ohlc, Mapping):
            ohlc = {}
        ltp = _num(raw.get("last_price"))
        day_open = _num(ohlc.get("open"))
        prev_close = _num(ohlc.get("close"))
        if ltp <= 0 or day_open <= 0:
            continue

        from_open = (ltp - day_open) / day_open * 100.0
        from_prev = ((ltp - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
        rows.append({
            "symbol": symbol,
            "security_id": sid,
            "ltp": round(ltp, 4),
            "day_open": round(day_open, 4),
            "previous_close": round(prev_close, 4),
            "from_open_pct": round(from_open, 4),
            "from_prev_close_pct": round(from_prev, 4),
        })

    up = sorted((r for r in rows if r["from_open_pct"] > 0),
                key=lambda r: r["from_open_pct"], reverse=True)[:max(1, top_n)]
    down = sorted((r for r in rows if r["from_open_pct"] < 0),
                  key=lambda r: r["from_open_pct"])[:max(1, top_n)]

    for rank, row in enumerate(up, 1):
        row["v2_side"] = "UP"
        row["v2_rank"] = rank
        row["eligible_option_side"] = "CE"
    for rank, row in enumerate(down, 1):
        row["v2_side"] = "DOWN"
        row["v2_rank"] = rank
        row["eligible_option_side"] = "PE"

    return {
        "top_n_per_side": max(1, top_n),
        "top_up": up,
        "top_down": down,
        "symbols": [r["symbol"] for r in up + down],
        "universe_rows_ranked": len(rows),
    }


def evaluate_entry_ready(
    *,
    candidates: Sequence[Any],
    mover_ranking: Mapping[str, Any],
    now: datetime,
    config: V2GateConfig | None = None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    cfg = config or V2GateConfig()
    up = {str(x.get("symbol") or ""): x for x in mover_ranking.get("top_up", [])}
    down = {str(x.get("symbol") or ""): x for x in mover_ranking.get("top_down", [])}

    passed: list[Any] = []
    blocked: list[dict[str, Any]] = []

    for c in candidates:
        symbol = str(getattr(c, "symbol", "") or "").upper()
        direction = str(getattr(c, "direction", "") or "").upper()
        reasons: list[str] = []

        expected = up.get(symbol) if direction == "BULLISH" else down.get(symbol)
        if expected is None:
            reasons.append("NOT_IN_DYNAMIC_TOP5_DIRECTION")

        directional_session = (
            _num(getattr(c, "move_from_0915_open_percent", 0.0))
            if direction == "BULLISH"
            else -_num(getattr(c, "move_from_0915_open_percent", 0.0))
        )
        d5 = (
            _num(getattr(c, "recent_move_5m_percent", 0.0))
            if direction == "BULLISH"
            else -_num(getattr(c, "recent_move_5m_percent", 0.0))
        )
        d10 = (
            _num(getattr(c, "recent_move_10m_percent", 0.0))
            if direction == "BULLISH"
            else -_num(getattr(c, "recent_move_10m_percent", 0.0))
        )
        d15 = (
            _num(getattr(c, "recent_move_15m_percent", 0.0))
            if direction == "BULLISH"
            else -_num(getattr(c, "recent_move_15m_percent", 0.0))
        )

        if directional_session < cfg.minimum_session_move_pct:
            reasons.append(
                f"SESSION_MOVE_TOO_SMALL({directional_session:.2f}%<{cfg.minimum_session_move_pct:.2f}%)"
            )
        if d5 < -cfg.maximum_opposing_5m_pct:
            reasons.append(f"CURRENT_5M_REVERSING({d5:.2f}%)")

        completed = int(_num(getattr(c, "completed_5m_bars", 0), 0))
        continuation_votes = int(d5 >= 0.03) + int(d10 >= cfg.minimum_recent_10m_pct)
        if completed >= 3:
            continuation_votes += int(d15 >= cfg.minimum_recent_15m_pct)
        fresh_edge = (
            bool(getattr(c, "fresh_15m_high", False))
            if direction == "BULLISH"
            else bool(getattr(c, "fresh_15m_low", False))
        )
        if fresh_edge:
            continuation_votes += 1
        minimum_votes = 2
        if continuation_votes < minimum_votes:
            reasons.append(
                f"NO_FRESH_CONTINUATION(votes={continuation_votes}/{minimum_votes},"
                f"5m={d5:.2f},10m={d10:.2f},15m={d15:.2f})"
            )

        participation = max(
            _num(getattr(c, "relative_volume", 0.0)),
            _num(getattr(c, "recent_relative_volume_15m", 0.0)),
            _num(getattr(c, "tape_volume_acceleration_5m", 0.0)),
            _num(getattr(c, "tape_volume_acceleration_15m", 0.0)),
        )
        if participation < cfg.minimum_participation:
            reasons.append(
                f"PARTICIPATION_TOO_LOW({participation:.2f}x<{cfg.minimum_participation:.2f}x)"
            )

        retention = _num(getattr(c, "trend_retention_percent", 0.0))
        if retention < cfg.minimum_trend_retention_pct:
            reasons.append(
                f"TREND_NOT_RETAINED({retention:.1f}%<{cfg.minimum_trend_retention_pct:.1f}%)"
            )

        if reasons:
            blocked.append({
                "symbol": symbol,
                "direction": direction,
                "stage": str(getattr(c, "stage", "") or ""),
                "setup_family": str(getattr(c, "setup_family", "") or ""),
                "move_from_0915_open_pct": round(directional_session, 4),
                "directional_5m_pct": round(d5, 4),
                "directional_10m_pct": round(d10, 4),
                "directional_15m_pct": round(d15, 4),
                "participation": round(participation, 4),
                "trend_retention_pct": round(retention, 2),
                "reasons": reasons,
            })
            continue

        passed.append(c)

    return passed, blocked
