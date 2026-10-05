"""Read-only browser alert evaluation for the APlus dashboard.

This module never places orders, sends Telegram messages, or changes scanner state.
It evaluates fields already present in the market-watch snapshot and safely skips
rules whose required indicator data is not available yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AlertRule:
    rule_id: str
    category: str
    label: str
    aliases: tuple[str, ...]
    direction: str = "INFO"


RULES: tuple[AlertRule, ...] = (
    AlertRule("range_5d_bo", "Range Breakout", "5 Days BO", ("range_5d_breakout", "breakout_5d", "bo_5d"), "UP"),
    AlertRule("range_5d_bd", "Range Breakout", "5 Days BD", ("range_5d_breakdown", "breakdown_5d", "bd_5d"), "DOWN"),
    AlertRule("range_10d_bo", "Range Breakout", "10 Days BO", ("range_10d_breakout", "breakout_10d", "bo_10d"), "UP"),
    AlertRule("range_10d_bd", "Range Breakout", "10 Days BD", ("range_10d_breakdown", "breakdown_10d", "bd_10d"), "DOWN"),
    AlertRule("range_30d_bo", "Range Breakout", "30 Days BO", ("range_30d_breakout", "breakout_30d", "bo_30d"), "UP"),
    AlertRule("range_30d_bd", "Range Breakout", "30 Days BD", ("range_30d_breakdown", "breakdown_30d", "bd_30d"), "DOWN"),
    AlertRule("range_90d_bo", "Range Breakout", "90 Days BO", ("range_90d_breakout", "breakout_90d", "bo_90d"), "UP"),
    AlertRule("range_90d_bd", "Range Breakout", "90 Days BD", ("range_90d_breakdown", "breakdown_90d", "bd_90d"), "DOWN"),
    AlertRule("range_52w_bo", "Range Breakout", "52 Week BO", ("range_52w_breakout", "breakout_52w", "bo_52w"), "UP"),
    AlertRule("range_52w_bd", "Range Breakout", "52 Week BD", ("range_52w_breakdown", "breakdown_52w", "bd_52w"), "DOWN"),
    AlertRule("dma_200_bo", "Moving Average Breakout", "200 DMA BO/BD", ("dma200_breakout", "dma_200_breakout", "above_200_dma", "below_200_dma")),
    AlertRule("dma_100_bo", "Moving Average Breakout", "100 DMA BO/BD", ("dma100_breakout", "dma_100_breakout", "above_100_dma", "below_100_dma")),
    AlertRule("dma_50_bo", "Moving Average Breakout", "50 DMA BO/BD", ("dma50_breakout", "dma_50_breakout", "above_50_dma", "below_50_dma")),
    AlertRule("ema_20_bo", "Moving Average Breakout", "20 EMA BO/BD", ("ema20_breakout", "ema_20_breakout", "above_20_ema", "below_20_ema")),
    AlertRule("supertrend", "Supertrend", "Supertrend close above/close below 1D", ("supertrend_direction", "supertrend_1d", "supertrend_signal")),
    AlertRule("volume_breakout_5m", "Volume Breakout", "Volume Breakout 5min", ("volume_breakout_5m", "volume_breakout", "volume_spike_5m")),
    AlertRule("day_high", "APlus Price", "Day High Breakout", ("day_high_breakout", "new_day_high"), "UP"),
    AlertRule("day_low", "APlus Price", "Day Low Breakdown", ("day_low_breakdown", "new_day_low"), "DOWN"),
    AlertRule("strong_up", "APlus Momentum", "Strong Up ≥ 1%", ("strong_up", "from_open_strong_up"), "UP"),
    AlertRule("strong_down", "APlus Momentum", "Strong Down ≤ −1%", ("strong_down", "from_open_strong_down"), "DOWN"),
    AlertRule("vwap_bull", "APlus Confirmation", "VWAP Bullish", ("vwap_bullish", "above_vwap"), "UP"),
    AlertRule("vwap_bear", "APlus Confirmation", "VWAP Bearish", ("vwap_bearish", "below_vwap"), "DOWN"),
    AlertRule("rvol_spike", "APlus Confirmation", "RVOL Spike ≥ 2x", ("rvol_spike", "relative_volume_spike", "rvat_spike"), "UP"),
    AlertRule("order_flow_bull", "APlus Confirmation", "Order Flow Bullish", ("order_flow_bullish", "order_flow_buying"), "UP"),
    AlertRule("order_flow_bear", "APlus Confirmation", "Order Flow Bearish", ("order_flow_bearish", "order_flow_selling"), "DOWN"),
    AlertRule("aplus_confirmed", "APlus Signal", "APlus Multi-Factor Confirmation", ("aplus_confirmed", "multi_factor_confirmed", "a_plus_confirmed"), "INFO"),
)


def _value(row: Mapping[str, Any], aliases: Sequence[str]) -> tuple[Any, str | None]:
    for key in aliases:
        if key not in row:
            continue
        value = row.get(key)
        if value is not None and value != "":
            return value, key
    return None, None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on", "up", "bullish", "breakout", "buy"}


def _fallback_rule(rule: AlertRule, row: Mapping[str, Any]) -> tuple[bool, str]:
    """Use current F&O market-watch fields where richer indicators aren't loaded."""
    from_open = row.get("from_open_pct")
    if rule.rule_id == "day_high":
        ltp, high = row.get("ltp"), row.get("day_high")
        return bool(ltp is not None and high not in (None, 0) and float(ltp) >= float(high)), "day_high"
    if rule.rule_id == "day_low":
        ltp, low = row.get("ltp"), row.get("day_low")
        return bool(ltp is not None and low not in (None, 0) and float(ltp) <= float(low)), "day_low"
    if rule.rule_id == "strong_up":
        return bool(from_open is not None and float(from_open) >= 1.0), "from_open_pct"
    if rule.rule_id == "strong_down":
        return bool(from_open is not None and float(from_open) <= -1.0), "from_open_pct"
    return False, ""


def evaluate_rule(rule: AlertRule, row: Mapping[str, Any]) -> tuple[bool, str]:
    value, key = _value(row, rule.aliases)
    if key is not None:
        return _truthy(value), key
    return _fallback_rule(rule, row)


def evaluate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        for rule in RULES:
            triggered, source_key = evaluate_rule(rule, row)
            if not triggered:
                continue
            alerts.append({
                "alert_id": f"{rule.rule_id}:{symbol}",
                "rule_id": rule.rule_id,
                "category": rule.category,
                "label": rule.label,
                "direction": rule.direction,
                "symbol": symbol,
                "ltp": row.get("ltp"),
                "from_open_pct": row.get("from_open_pct"),
                "source_key": source_key,
                "generated_at": row.get("generated_at") or datetime.now().isoformat(),
                "read_only": True,
                "telegram": False,
            })
    return alerts


def rule_catalog(rows: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    sample = rows[0] if rows else {}
    return [
        {
            "rule_id": rule.rule_id,
            "category": rule.category,
            "label": rule.label,
            "available": any(k in sample for k in rule.aliases)
            or rule.rule_id in {"day_high", "day_low", "strong_up", "strong_down"},
            "direction": rule.direction,
            "browser_only": True,
            "telegram": False,
        }
        for rule in RULES
    ]


__all__ = ["RULES", "AlertRule", "evaluate_rows", "rule_catalog"]
