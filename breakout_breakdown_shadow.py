"""Isolated, non-authorizing 3-minute NSE breakout/breakdown research module."""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

@dataclass(frozen=True, slots=True)
class MinuteBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

@dataclass(frozen=True, slots=True)
class ThreeMinuteBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

@dataclass(frozen=True, slots=True)
class BreakoutConfig:
    lookback_bars: int = 5
    breakout_buffer_pct: float = 0.05
    minimum_relative_volume: float = 1.30
    minimum_score: float = 70.0
    minimum_close_location: float = 0.70
    minimum_body_ratio: float = 0.35
    maximum_vwap_extension_pct: float = 2.50
    minimum_history_sessions: int = 5

    def __post_init__(self) -> None:
        if self.lookback_bars < 2 or self.breakout_buffer_pct < 0:
            raise ValueError("Invalid lookback or breakout buffer")
        if self.minimum_relative_volume <= 0:
            raise ValueError("minimum_relative_volume must be > 0")
        if not 0 <= self.minimum_score <= 100:
            raise ValueError("minimum_score must be between 0 and 100")
        if not 0.5 <= self.minimum_close_location <= 1:
            raise ValueError("minimum_close_location must be between 0.5 and 1")
        if not 0 <= self.minimum_body_ratio <= 1:
            raise ValueError("minimum_body_ratio must be between 0 and 1")
        if self.maximum_vwap_extension_pct <= 0 or self.minimum_history_sessions < 1:
            raise ValueError("Invalid VWAP extension or history requirement")

def _get(raw: Any, name: str) -> Any:
    return raw[name] if isinstance(raw, Mapping) else getattr(raw, name)

def _ist(value: datetime) -> datetime:
    return value.replace(tzinfo=IST) if value.tzinfo is None else value.astimezone(IST)

def _normalise_minute(raw: Any) -> MinuteBar:
    ts = _ist(_get(raw, "timestamp")).replace(second=0, microsecond=0)
    o, h, lo, c = (float(_get(raw, k)) for k in ("open", "high", "low", "close"))
    volume = int(_get(raw, "volume"))
    if min(o, h, lo, c) <= 0 or volume < 0 or h < max(o, c, lo) or lo > min(o, c, h):
        raise ValueError("Invalid OHLCV bar")
    return MinuteBar(ts, o, h, lo, c, volume)

def aggregate_three_minute_bars(
    bars: Iterable[Any], *, session_start: time = time(9, 15),
    session_end: time = time(15, 30),
) -> list[ThreeMinuteBar]:
    """Aggregate complete session-aligned buckets; omit buckets with missing minutes.

    Naive timestamps are interpreted as IST. Duplicate timestamps keep the last row.
    Output timestamps represent the start of each 3-minute bucket.
    """
    by_time: dict[datetime, MinuteBar] = {}
    for raw in bars:
        try:
            bar = _normalise_minute(raw)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if session_start <= bar.timestamp.time() < session_end:
            by_time[bar.timestamp] = bar
    groups: dict[datetime, list[MinuteBar]] = {}
    for bar in by_time.values():
        start = datetime.combine(bar.timestamp.date(), session_start, tzinfo=IST)
        elapsed = int((bar.timestamp - start).total_seconds() // 60)
        bucket = start + timedelta(minutes=(elapsed // 3) * 3)
        groups.setdefault(bucket, []).append(bar)
    result = []
    for start in sorted(groups):
        group = sorted(groups[start], key=lambda b: b.timestamp)
        expected = [start + timedelta(minutes=i) for i in range(3)]
        if len(group) != 3 or [b.timestamp for b in group] != expected:
            continue
        result.append(ThreeMinuteBar(start, group[0].open, max(b.high for b in group),
                                     min(b.low for b in group), group[-1].close,
                                     sum(b.volume for b in group)))
    return result

def same_slot_relative_volume(
    current_volume: int, historical_same_slot_volumes: Sequence[int | float],
    *, minimum_sessions: int = 5,
) -> float | None:
    """Return current volume / median same-slot volume; None if history is insufficient."""
    if current_volume < 0 or minimum_sessions < 1:
        return None
    values = []
    for raw in historical_same_slot_volumes:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    if len(values) < minimum_sessions:
        return None
    baseline = median(values)
    return float(current_volume) / baseline if baseline > 0 else None

@dataclass(frozen=True, slots=True)
class ShadowSignal:
    symbol: str
    timestamp: str
    direction: str
    verdict: str
    score: float
    trigger_level: float | None
    close: float
    relative_volume: float | None
    vwap: float | None
    reasons: tuple[str, ...]
    shadow_only: bool = True
    trade_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def classify_breakout_breakdown(
    *, symbol: str, bars: Sequence[ThreeMinuteBar],
    relative_volume: float | None, vwap: float | None,
    config: BreakoutConfig = BreakoutConfig(),
) -> ShadowSignal:
    """Classify latest completed bar. This function never authorizes a trade."""
    symbol = str(symbol).strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    if len(bars) < config.lookback_bars + 1:
        last = bars[-1] if bars else None
        return ShadowSignal(symbol, last.timestamp.isoformat() if last else "", "NONE",
            "DATA_INSUFFICIENT", 0.0, None, last.close if last else 0.0, relative_volume,
            vwap, (f"Need {config.lookback_bars + 1} completed bars",))
    last = bars[-1]
    prior = bars[-config.lookback_bars-1:-1]
    resistance, support = max(b.high for b in prior), min(b.low for b in prior)
    if last.close > resistance * (1 + config.breakout_buffer_pct / 100):
        direction, trigger = "BULLISH", resistance
    elif last.close < support * (1 - config.breakout_buffer_pct / 100):
        direction, trigger = "BEARISH", support
    else:
        return ShadowSignal(symbol, last.timestamp.isoformat(), "NONE", "NO_BREAKOUT", 0,
            None, last.close, relative_volume, vwap, ("Close remains inside prior range",))
    reasons = [f"Close broke {'above resistance' if direction == 'BULLISH' else 'below support'}"]
    score = 30.0
    if relative_volume is None or relative_volume <= 0:
        return ShadowSignal(symbol, last.timestamp.isoformat(), direction, "DATA_INSUFFICIENT",
            score, trigger, last.close, relative_volume, vwap,
            tuple(reasons + ["Missing same-time-slot historical relative-volume baseline"]))
    if relative_volume < config.minimum_relative_volume:
        return ShadowSignal(symbol, last.timestamp.isoformat(), direction, "LOW_VOLUME_REJECT",
            score, trigger, last.close, relative_volume, vwap,
            tuple(reasons + [f"Relative volume {relative_volume:.2f}x below minimum"]))
    score += 20
    reasons.append(f"Relative volume confirmed: {relative_volume:.2f}x")
    candle_range = max(last.high - last.low, 1e-9)
    if direction == "BULLISH":
        close_location = (last.close - last.low) / candle_range
        aligned = sum(a.close >= b.close for a, b in zip(bars[-4:-1], bars[-3:]))
        directional_body = last.close > last.open
        vwap_aligned = vwap is not None and vwap > 0 and last.close >= vwap
        extension = (last.close-vwap)/vwap*100 if vwap is not None and vwap > 0 else None
    else:
        close_location = (last.high - last.close) / candle_range
        aligned = sum(a.close <= b.close for a, b in zip(bars[-4:-1], bars[-3:]))
        directional_body = last.close < last.open
        vwap_aligned = vwap is not None and vwap > 0 and last.close <= vwap
        extension = (vwap-last.close)/vwap*100 if vwap is not None and vwap > 0 else None
    if close_location >= config.minimum_close_location:
        score += 15
        reasons.append("Close near directional candle extreme")
    else:
        reasons.append("Weak candle close location")
    body_ratio = abs(last.close-last.open)/candle_range
    if directional_body and body_ratio >= config.minimum_body_ratio:
        score += 15
        reasons.append("Directional body confirmed")
    else:
        reasons.append("Directional candle body weak or opposing")
    if aligned >= 2:
        score += 10
        reasons.append("Recent closes align with direction")
    else:
        reasons.append("Short-term trend alignment weak")
    if vwap is not None and vwap > 0:
        if vwap_aligned:
            score += 10
            reasons.append("VWAP supports direction")
        else:
            reasons.append("VWAP conflicts with direction")
        if extension is not None and extension > config.maximum_vwap_extension_pct:
            return ShadowSignal(symbol, last.timestamp.isoformat(), direction, "CHASE_RISK_REJECT",
                round(score, 2), trigger, last.close, relative_volume, vwap,
                tuple(reasons + [f"VWAP extension {extension:.2f}% exceeds limit"]))
    else:
        reasons.append("VWAP unavailable; no VWAP score awarded")
    verdict = "SHADOW_CONFIRMED" if score >= config.minimum_score else "WATCH_WEAK_BREAK"
    return ShadowSignal(symbol, last.timestamp.isoformat(), direction, verdict, min(round(score, 2), 100),
                        trigger, last.close, relative_volume, vwap, tuple(reasons))

def evaluate_forward_outcome(
    *, signal: ShadowSignal, entry_price: float, future_bars: Sequence[ThreeMinuteBar],
    horizon_bars: int = 5,
) -> dict[str, Any]:
    """Measure underlying MFE/MAE for research; not an option-return or exit rule."""
    if entry_price <= 0 or horizon_bars < 1:
        raise ValueError("entry_price and horizon_bars must be positive")
    window = list(future_bars[:horizon_bars])
    if signal.timestamp:
        try:
            signal_time = _ist(datetime.fromisoformat(signal.timestamp))
        except (TypeError, ValueError):
            raise ValueError("signal.timestamp must be a valid ISO timestamp")
        normalised_times = [_ist(bar.timestamp) for bar in window]
        if any(ts <= signal_time for ts in normalised_times):
            raise ValueError("future_bars must occur strictly after the signal timestamp")
        if any(a >= b for a, b in zip(normalised_times, normalised_times[1:])):
            raise ValueError("future_bars must be in strictly increasing timestamp order")
    if not window or signal.direction not in {"BULLISH", "BEARISH"}:
        return {"outcome": "PENDING_OR_NOT_DIRECTIONAL", "bars_observed": len(window),
                "mfe_percent": None, "mae_percent": None, "close_return_percent": None}
    if signal.direction == "BULLISH":
        mfe = (max(b.high for b in window)/entry_price-1)*100
        mae = (min(b.low for b in window)/entry_price-1)*100
        close_return = (window[-1].close/entry_price-1)*100
    else:
        mfe = (entry_price-min(b.low for b in window))/entry_price*100
        mae = (entry_price-max(b.high for b in window))/entry_price*100
        close_return = (entry_price-window[-1].close)/entry_price*100
    return {"outcome": "OBSERVED", "bars_observed": len(window),
            "mfe_percent": round(mfe, 4), "mae_percent": round(mae, 4),
            "close_return_percent": round(close_return, 4),
            "horizon_complete": len(window) >= horizon_bars}

def append_shadow_record(
    path: str | Path, signal: ShadowSignal, outcome: Mapping[str, Any] | None = None,
) -> None:
    """Append JSONL to a separate shadow ledger; reject any trade-authorizing signal."""
    if not signal.shadow_only or signal.trade_authorized:
        raise ValueError("Shadow ledger accepts only non-authorizing shadow signals")
    record: dict[str, Any] = {"record_type": "signal", **signal.to_dict()}
    if outcome is not None:
        record["outcome"] = dict(outcome)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
