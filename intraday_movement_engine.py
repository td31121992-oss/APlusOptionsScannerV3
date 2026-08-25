"""
intraday_movement_engine.py

Stateful all-day intraday feature engine for APlus Options Scanner V3.

The engine is intentionally broker-order agnostic.  It keeps a lightweight quote
"tape" for the full F&O universe so a stock that wakes up at 11:30, 13:15 or
14:20 can enter the radar even when its total move from the 09:15 open is still
small.  Detailed 5-minute/15-minute features are then calculated only for the
scanner's candle shortlist.

PAPER/ANALYTICS ONLY -- this module never places an order.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence


@dataclass(slots=True)
class TapeMetrics:
    move_5m_percent: float = 0.0
    move_10m_percent: float = 0.0
    move_15m_percent: float = 0.0
    move_30m_percent: float = 0.0
    volume_5m: int = 0
    volume_15m: int = 0
    volume_acceleration_5m: float = 1.0
    volume_acceleration_15m: float = 1.0
    samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IntradayFeatures:
    recent_move_5m_percent: float = 0.0
    recent_move_10m_percent: float = 0.0
    recent_move_15m_percent: float = 0.0
    recent_move_30m_percent: float = 0.0
    tape_volume_acceleration_5m: float = 1.0
    tape_volume_acceleration_15m: float = 1.0
    recent_relative_volume_15m: float = 0.0

    ema9_5m: float = 0.0
    ema20_5m: float = 0.0
    ema50_5m: float = 0.0
    ema9_15m: float = 0.0
    ema20_15m: float = 0.0
    rsi14_5m: float = 50.0
    adx14_5m: float = 0.0
    plus_di_5m: float = 0.0
    minus_di_5m: float = 0.0

    pivot_point: float = 0.0
    r1: float = 0.0
    r2: float = 0.0
    r3: float = 0.0
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    pivot_state: str = "PIVOT_UNKNOWN"

    fresh_15m_high: bool = False
    fresh_15m_low: bool = False
    fresh_30m_high: bool = False
    fresh_30m_low: bool = False
    fresh_day_high: bool = False
    fresh_day_low: bool = False

    five_minute_structure_ratio: float = 0.0
    fifteen_minute_structure_ratio: float = 0.0
    trend_alignment_score: float = 0.0
    clean_trend_score: float = 0.0
    chase_risk_score: float = 0.0

    fresh_breakout: bool = False
    healthy_pullback: bool = False
    continuation_breakout: bool = False
    setup_family: str = "TREND_MONITORING"
    selection_tier: str = "WATCH"
    previous_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QuoteTape:
    """Persist the last hour of one-minute-ish quote observations.

    The scanner normally polls every 60 seconds, but the implementation does
    not assume an exact cadence.  For each lookback it chooses the latest sample
    at or before the target timestamp.
    """

    def __init__(self, path: Path, *, keep_minutes: int = 65) -> None:
        self.path = Path(path)
        self.keep_minutes = max(35, int(keep_minutes))
        self.session_date: str = ""
        self.samples: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def observe(
        self,
        *,
        symbol: str,
        when: datetime,
        ltp: float,
        volume: int,
    ) -> TapeMetrics:
        symbol = str(symbol).strip().upper()
        session_date = when.date().isoformat()
        if self.session_date != session_date:
            self.session_date = session_date
            self.samples = {}

        rows = self.samples.setdefault(symbol, [])
        current = {
            "ts": when.isoformat(),
            "ltp": float(ltp),
            "volume": max(0, int(volume)),
        }

        # Replace an observation from the same minute rather than growing the
        # tape when a manual one-shot is run repeatedly within that minute.
        minute_key = when.replace(second=0, microsecond=0)
        if rows:
            try:
                last_when = datetime.fromisoformat(str(rows[-1].get("ts")))
            except Exception:
                last_when = None
            if last_when is not None and last_when.replace(second=0, microsecond=0) == minute_key:
                rows[-1] = current
            else:
                rows.append(current)
        else:
            rows.append(current)

        cutoff = when - timedelta(minutes=self.keep_minutes)
        rows[:] = [
            row for row in rows
            if self._row_time(row) is not None and self._row_time(row) >= cutoff
        ]

        return self._metrics(rows, when)

    def flush(self) -> None:
        payload = {
            "session_date": self.session_date,
            "samples": self.samples,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=self.path.name,
            suffix=".tmp",
            dir=self.path.parent,
        )
        os.close(fd)
        temporary = Path(temp_name)
        try:
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            session_date = str(payload.get("session_date") or "")
            samples = payload.get("samples") or {}
            if session_date and isinstance(samples, Mapping):
                self.session_date = session_date
                self.samples = {
                    str(symbol).upper(): list(rows or [])
                    for symbol, rows in samples.items()
                    if isinstance(rows, list)
                }
        except Exception:
            # A damaged tape must never stop the scanner.  It simply starts a
            # new observation history and rebuilds itself during the session.
            self.session_date = ""
            self.samples = {}

    @classmethod
    def _metrics(
        cls,
        rows: Sequence[Mapping[str, Any]],
        when: datetime,
    ) -> TapeMetrics:
        if not rows:
            return TapeMetrics()
        current = rows[-1]
        current_price = cls._number(current.get("ltp"))
        current_volume = max(0, int(cls._number(current.get("volume"))))

        def prior(minutes: int) -> Mapping[str, Any] | None:
            target = when - timedelta(minutes=minutes)
            eligible: list[Mapping[str, Any]] = []
            for row in rows:
                ts = cls._row_time(row)
                if ts is not None and ts <= target:
                    eligible.append(row)
            return eligible[-1] if eligible else None

        def move(minutes: int) -> float:
            row = prior(minutes)
            if row is None:
                return 0.0
            old = cls._number(row.get("ltp"))
            if old <= 0:
                return 0.0
            return (current_price - old) / old * 100.0

        def volume_delta(minutes: int) -> int:
            row = prior(minutes)
            if row is None:
                return 0
            old = max(0, int(cls._number(row.get("volume"))))
            return max(0, current_volume - old)

        v5 = volume_delta(5)
        v15 = volume_delta(15)
        previous_20 = max(0, volume_delta(25) - v5)
        prior_5_average = previous_20 / 4.0 if previous_20 > 0 else 0.0
        accel5 = v5 / prior_5_average if prior_5_average > 0 else 1.0

        previous_30 = max(0, volume_delta(45) - v15)
        prior_15_average = previous_30 / 2.0 if previous_30 > 0 else 0.0
        accel15 = v15 / prior_15_average if prior_15_average > 0 else 1.0

        return TapeMetrics(
            move_5m_percent=move(5),
            move_10m_percent=move(10),
            move_15m_percent=move(15),
            move_30m_percent=move(30),
            volume_5m=v5,
            volume_15m=v15,
            volume_acceleration_5m=max(0.0, min(20.0, accel5)),
            volume_acceleration_15m=max(0.0, min(20.0, accel15)),
            samples=len(rows),
        )

    @staticmethod
    def _row_time(row: Mapping[str, Any]) -> datetime | None:
        try:
            return datetime.fromisoformat(str(row.get("ts") or ""))
        except Exception:
            return None

    @staticmethod
    def _number(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        return number if math.isfinite(number) else 0.0


class SessionStateStore:
    """Small persistent per-symbol state machine memory."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.session_date: str = ""
        self.states: dict[str, dict[str, Any]] = {}
        self._load()

    def previous_state(self, symbol: str, when: datetime) -> str:
        self._ensure_date(when.date())
        item = self.states.get(str(symbol).upper(), {})
        return str(item.get("current_state") or "")

    def update(
        self,
        *,
        symbol: str,
        stage: str,
        direction: str,
        movement_score: float,
        trade_quality_score: float,
        actionable: bool,
        setup_family: str,
        when: datetime,
    ) -> dict[str, Any]:
        self._ensure_date(when.date())
        key = str(symbol).upper()
        previous = self.states.get(key, {})
        previous_stage = str(previous.get("current_state") or "")
        first_movement_time = previous.get("first_movement_time")
        if not first_movement_time and movement_score >= 55:
            first_movement_time = when.isoformat()

        latest_acceleration = previous.get("latest_acceleration_time")
        if setup_family in {"FRESH_BREAKOUT", "CONTINUATION_BREAKOUT"}:
            latest_acceleration = when.isoformat()

        last_pullback = previous.get("last_pullback_time")
        if "PULLBACK" in stage:
            last_pullback = when.isoformat()

        last_breakout = previous.get("last_breakout_time")
        if "BREAKOUT" in stage or "BREAKDOWN" in stage:
            last_breakout = when.isoformat()

        item = {
            "symbol": key,
            "direction": direction,
            "previous_state": previous_stage,
            "current_state": stage,
            "first_movement_time": first_movement_time or "",
            "latest_acceleration_time": latest_acceleration or "",
            "last_breakout_time": last_breakout or "",
            "last_pullback_time": last_pullback or "",
            "highest_movement_score": max(
                float(previous.get("highest_movement_score") or 0.0),
                float(movement_score),
            ),
            "highest_trade_quality": max(
                float(previous.get("highest_trade_quality") or 0.0),
                float(trade_quality_score),
            ),
            "last_signal_time": when.isoformat() if actionable else str(previous.get("last_signal_time") or ""),
            "updated_at": when.isoformat(),
        }
        self.states[key] = item
        return item

    def flush(self) -> None:
        payload = {
            "session_date": self.session_date,
            "states": self.states,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=self.path.name,
            suffix=".tmp",
            dir=self.path.parent,
        )
        os.close(fd)
        temporary = Path(temp_name)
        try:
            temporary.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _ensure_date(self, value: date) -> None:
        key = value.isoformat()
        if self.session_date != key:
            self.session_date = key
            self.states = {}

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            states = payload.get("states") or {}
            if isinstance(states, Mapping):
                self.session_date = str(payload.get("session_date") or "")
                self.states = {
                    str(symbol).upper(): dict(item or {})
                    for symbol, item in states.items()
                    if isinstance(item, Mapping)
                }
        except Exception:
            self.session_date = ""
            self.states = {}


class IntradayMovementEngine:
    """Calculate all-day 5m/15m features and maintain scanner state."""

    def __init__(self, *, state_dir: Path, settings: Any) -> None:
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        keep_minutes = int(getattr(settings, "quote_tape_minutes", 65))
        self.settings = settings
        self.tape = QuoteTape(
            state_dir / "quote_tape.json",
            keep_minutes=keep_minutes,
        )
        self.state = SessionStateStore(state_dir / "session_state.json")

    def observe_quote(
        self,
        *,
        symbol: str,
        when: datetime,
        ltp: float,
        volume: int,
    ) -> TapeMetrics:
        return self.tape.observe(
            symbol=symbol,
            when=when,
            ltp=ltp,
            volume=volume,
        )

    def analyse(
        self,
        *,
        symbol: str,
        direction: str,
        price: float,
        vwap: float,
        completed: Sequence[Any],
        grouped: Mapping[date, Sequence[Any]],
        current_date: date,
        now: datetime,
        range_position_percent: float,
        trend_retention_percent: float,
        extension_atr: float,
        vwap_distance_percent: float,
        tape_metrics: TapeMetrics | Mapping[str, Any] | None = None,
    ) -> IntradayFeatures:
        previous_state = self.state.previous_state(symbol, now)
        tape = self._coerce_tape(tape_metrics)

        closes = [float(c.close) for c in completed]
        highs = [float(c.high) for c in completed]
        lows = [float(c.low) for c in completed]
        closes_with_price = closes + ([float(price)] if not closes or abs(closes[-1] - price) > 1e-9 else [])

        ema9 = self._ema(closes_with_price, 9)
        ema20 = self._ema(closes_with_price, 20)
        ema50 = self._ema(closes_with_price, 50)

        bars15 = self._aggregate_15m(completed)
        closes15 = [float(c[3]) for c in bars15]
        if closes15 and abs(closes15[-1] - price) > 1e-9:
            closes15 = closes15 + [float(price)]
        ema9_15 = self._ema(closes15, 9)
        ema20_15 = self._ema(closes15, 20)

        rsi = self._rsi(closes_with_price, 14)
        adx, plus_di, minus_di = self._adx(completed, 14)

        pivots = self._previous_session_pivots(grouped, current_date)
        pivot_state = self._pivot_state(price, pivots)

        recent5 = self._recent_move(price, completed, 1)
        recent10 = self._recent_move(price, completed, 2)
        recent15 = self._recent_move(price, completed, 3)
        recent30 = self._recent_move(price, completed, 6)
        # Quote tape is more responsive between candle closes.  Prefer the
        # larger absolute move from either source, preserving its sign.
        recent5 = self._stronger(recent5, tape.move_5m_percent)
        recent10 = self._stronger(recent10, tape.move_10m_percent)
        recent15 = self._stronger(recent15, tape.move_15m_percent)
        recent30 = self._stronger(recent30, tape.move_30m_percent)

        recent_rvol15 = self._recent_relative_volume(
            completed=completed,
            grouped=grouped,
            current_date=current_date,
            window_bars=3,
        )

        fresh15h = self._breaks_recent(price, completed, 3, bullish=True)
        fresh15l = self._breaks_recent(price, completed, 3, bullish=False)
        fresh30h = self._breaks_recent(price, completed, 6, bullish=True)
        fresh30l = self._breaks_recent(price, completed, 6, bullish=False)
        session_high = max(highs) if highs else price
        session_low = min(lows) if lows else price
        fresh_day_high = price >= session_high
        fresh_day_low = price <= session_low

        structure5 = self._structure_ratio(completed[-6:], direction)
        structure15 = self._structure_ratio_15m(bars15[-5:], direction)

        effective_recent_rvol = max(
            recent_rvol15,
            tape.volume_acceleration_15m,
            tape.volume_acceleration_5m,
        )
        alignment = self._trend_alignment_score(
            direction=direction,
            price=price,
            vwap=vwap,
            ema9=ema9,
            ema20=ema20,
            ema50=ema50,
            ema9_15=ema9_15,
            ema20_15=ema20_15,
            adx=adx,
            plus_di=plus_di,
            minus_di=minus_di,
            rsi=rsi,
            structure5=structure5,
            structure15=structure15,
            recent_rvol=effective_recent_rvol,
        )
        clean = self._clean_trend_score(
            direction=direction,
            price=price,
            vwap=vwap,
            ema20=ema20,
            pivot_state=pivot_state,
            range_position_percent=range_position_percent,
            trend_retention_percent=trend_retention_percent,
            structure5=structure5,
        )
        chase = self._chase_risk_score(
            direction=direction,
            pivot_state=pivot_state,
            rsi=rsi,
            extension_atr=extension_atr,
            vwap_distance_percent=vwap_distance_percent,
            recent15=recent15,
            range_position_percent=range_position_percent,
            completed=completed,
        )

        directional_recent15 = recent15 if direction == "BULLISH" else -recent15
        directional_recent5 = recent5 if direction == "BULLISH" else -recent5
        recent_threshold = float(
            getattr(self.settings, "minimum_recent_move_15m_percent", 0.45)
        )
        rvol_threshold = float(
            getattr(self.settings, "minimum_recent_volume_acceleration", 1.30)
        )
        breakout = (
            directional_recent15 >= recent_threshold
            and effective_recent_rvol >= rvol_threshold
            and (fresh15h if direction == "BULLISH" else fresh15l)
        )

        atr_proxy = self._median_true_range(completed[-20:])
        healthy_pullback = self._healthy_pullback(
            direction=direction,
            price=price,
            vwap=vwap,
            ema20=ema20,
            atr=atr_proxy,
            recent5=recent5,
            completed=completed,
            previous_state=previous_state,
        )
        continuation = self._continuation_breakout(
            direction=direction,
            price=price,
            recent5=recent5,
            completed=completed,
            previous_state=previous_state,
            healthy_pullback=healthy_pullback,
        )

        if continuation:
            family = "CONTINUATION_BREAKOUT"
            tier = "CONTINUATION_ENTRY"
        elif breakout:
            family = "FRESH_BREAKOUT"
            tier = "FRESH_INTRADAY_BREAKOUT"
        elif healthy_pullback:
            family = "HEALTHY_PULLBACK"
            tier = "WAIT_FOR_RETEST"
        elif alignment >= 65 or clean >= 70:
            family = "ESTABLISHED_TREND"
            tier = "TREND_MONITOR"
        else:
            family = "TREND_MONITORING"
            tier = "WATCH"

        return IntradayFeatures(
            recent_move_5m_percent=recent5,
            recent_move_10m_percent=recent10,
            recent_move_15m_percent=recent15,
            recent_move_30m_percent=recent30,
            tape_volume_acceleration_5m=tape.volume_acceleration_5m,
            tape_volume_acceleration_15m=tape.volume_acceleration_15m,
            recent_relative_volume_15m=recent_rvol15,
            ema9_5m=ema9,
            ema20_5m=ema20,
            ema50_5m=ema50,
            ema9_15m=ema9_15,
            ema20_15m=ema20_15,
            rsi14_5m=rsi,
            adx14_5m=adx,
            plus_di_5m=plus_di,
            minus_di_5m=minus_di,
            pivot_point=pivots.get("P", 0.0),
            r1=pivots.get("R1", 0.0),
            r2=pivots.get("R2", 0.0),
            r3=pivots.get("R3", 0.0),
            s1=pivots.get("S1", 0.0),
            s2=pivots.get("S2", 0.0),
            s3=pivots.get("S3", 0.0),
            pivot_state=pivot_state,
            fresh_15m_high=fresh15h,
            fresh_15m_low=fresh15l,
            fresh_30m_high=fresh30h,
            fresh_30m_low=fresh30l,
            fresh_day_high=fresh_day_high,
            fresh_day_low=fresh_day_low,
            five_minute_structure_ratio=structure5,
            fifteen_minute_structure_ratio=structure15,
            trend_alignment_score=alignment,
            clean_trend_score=clean,
            chase_risk_score=chase,
            fresh_breakout=breakout,
            healthy_pullback=healthy_pullback,
            continuation_breakout=continuation,
            setup_family=family,
            selection_tier=tier,
            previous_state=previous_state,
        )

    def update_state(
        self,
        *,
        symbol: str,
        stage: str,
        direction: str,
        movement_score: float,
        trade_quality_score: float,
        actionable: bool,
        setup_family: str,
        when: datetime,
    ) -> dict[str, Any]:
        return self.state.update(
            symbol=symbol,
            stage=stage,
            direction=direction,
            movement_score=movement_score,
            trade_quality_score=trade_quality_score,
            actionable=actionable,
            setup_family=setup_family,
            when=when,
        )

    def flush(self) -> None:
        self.tape.flush()
        self.state.flush()

    @staticmethod
    def _coerce_tape(value: TapeMetrics | Mapping[str, Any] | None) -> TapeMetrics:
        if isinstance(value, TapeMetrics):
            return value
        if isinstance(value, Mapping):
            kwargs = {}
            for name in TapeMetrics.__dataclass_fields__:
                kwargs[name] = value.get(name, getattr(TapeMetrics(), name))
            try:
                return TapeMetrics(**kwargs)
            except Exception:
                return TapeMetrics()
        return TapeMetrics()

    @staticmethod
    def _stronger(first: float, second: float) -> float:
        return second if abs(second) > abs(first) else first

    @staticmethod
    def _recent_move(price: float, completed: Sequence[Any], bars: int) -> float:
        if len(completed) < bars:
            return 0.0
        old = float(completed[-bars].close)
        if old <= 0:
            return 0.0
        return (float(price) - old) / old * 100.0

    @staticmethod
    def _ema(values: Sequence[float], period: int) -> float:
        clean = [float(v) for v in values if math.isfinite(float(v)) and float(v) > 0]
        if not clean:
            return 0.0
        alpha = 2.0 / (period + 1.0)
        value = clean[0]
        for item in clean[1:]:
            value = alpha * item + (1.0 - alpha) * value
        return value

    @staticmethod
    def _rsi(values: Sequence[float], period: int = 14) -> float:
        if len(values) < 2:
            return 50.0
        changes = [values[i] - values[i - 1] for i in range(1, len(values))]
        window = changes[-period:]
        gains = [max(0.0, x) for x in window]
        losses = [max(0.0, -x) for x in window]
        avg_gain = sum(gains) / max(1, len(window))
        avg_loss = sum(losses) / max(1, len(window))
        if avg_loss <= 1e-12:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    @staticmethod
    def _adx(candles: Sequence[Any], period: int = 14) -> tuple[float, float, float]:
        if len(candles) < 3:
            return 0.0, 0.0, 0.0
        trs: list[float] = []
        plus_dm: list[float] = []
        minus_dm: list[float] = []
        for i in range(1, len(candles)):
            current = candles[i]
            previous = candles[i - 1]
            up = float(current.high) - float(previous.high)
            down = float(previous.low) - float(current.low)
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
            tr = max(
                float(current.high) - float(current.low),
                abs(float(current.high) - float(previous.close)),
                abs(float(current.low) - float(previous.close)),
            )
            trs.append(max(0.0, tr))
        n = min(period, len(trs))
        tr_sum = sum(trs[-n:])
        if tr_sum <= 1e-12:
            return 0.0, 0.0, 0.0
        plus = 100.0 * sum(plus_dm[-n:]) / tr_sum
        minus = 100.0 * sum(minus_dm[-n:]) / tr_sum
        dx_values: list[float] = []
        # A compact rolling approximation is sufficient for ranking; it avoids
        # requiring a TA dependency and is deterministic for tests.
        start = max(1, len(candles) - period - 5)
        for end in range(start + 2, len(candles) + 1):
            sub = candles[max(0, end - period - 1):end]
            sub_tr = 0.0
            sub_p = 0.0
            sub_m = 0.0
            for j in range(1, len(sub)):
                up = float(sub[j].high) - float(sub[j - 1].high)
                down = float(sub[j - 1].low) - float(sub[j].low)
                sub_p += up if up > down and up > 0 else 0.0
                sub_m += down if down > up and down > 0 else 0.0
                sub_tr += max(
                    float(sub[j].high) - float(sub[j].low),
                    abs(float(sub[j].high) - float(sub[j - 1].close)),
                    abs(float(sub[j].low) - float(sub[j - 1].close)),
                )
            if sub_tr > 0:
                p = 100.0 * sub_p / sub_tr
                m = 100.0 * sub_m / sub_tr
                denom = p + m
                if denom > 0:
                    dx_values.append(100.0 * abs(p - m) / denom)
        adx = sum(dx_values[-period:]) / max(1, len(dx_values[-period:])) if dx_values else 0.0
        return min(100.0, adx), min(100.0, plus), min(100.0, minus)

    @staticmethod
    def _aggregate_15m(candles: Sequence[Any]) -> list[tuple[float, float, float, float, int]]:
        result: list[tuple[float, float, float, float, int]] = []
        for index in range(0, len(candles), 3):
            chunk = list(candles[index:index + 3])
            if len(chunk) < 3:
                continue
            result.append((
                float(chunk[0].open),
                max(float(c.high) for c in chunk),
                min(float(c.low) for c in chunk),
                float(chunk[-1].close),
                sum(int(c.volume) for c in chunk),
            ))
        return result

    @staticmethod
    def _previous_session_pivots(
        grouped: Mapping[date, Sequence[Any]],
        current_date: date,
    ) -> dict[str, float]:
        previous_dates = sorted((d for d in grouped if d < current_date), reverse=True)
        if not previous_dates:
            return {}
        session = list(grouped[previous_dates[0]])
        if not session:
            return {}
        high = max(float(c.high) for c in session)
        low = min(float(c.low) for c in session)
        close = float(session[-1].close)
        p = (high + low + close) / 3.0
        r1 = 2.0 * p - low
        s1 = 2.0 * p - high
        r2 = p + (high - low)
        s2 = p - (high - low)
        r3 = high + 2.0 * (p - low)
        s3 = low - 2.0 * (high - p)
        return {"P": p, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}

    @staticmethod
    def _pivot_state(price: float, pivots: Mapping[str, float]) -> str:
        if not pivots:
            return "PIVOT_UNKNOWN"
        r1, r2, r3 = pivots["R1"], pivots["R2"], pivots["R3"]
        s1, s2, s3 = pivots["S1"], pivots["S2"], pivots["S3"]
        p = pivots["P"]
        if price >= r3:
            return "ABOVE_R3"
        if price >= r2:
            return "R2_TO_R3"
        if price >= r1:
            return "R1_TO_R2"
        if price >= p:
            return "PIVOT_TO_R1"
        if price > s1:
            return "S1_TO_PIVOT"
        if price > s2:
            return "S2_TO_S1"
        if price > s3:
            return "S3_TO_S2"
        return "BELOW_S3"

    # APLUS_BREAKOUT_CONFIRMATION_V1
    @staticmethod
    def _breakout_clearance(level: float, candles: Sequence[Any]) -> float:
        rows=list(candles)
        ranges=sorted(
            max(0.0, float(c.high)-float(c.low))
            for c in rows
            if float(c.high)>0 and float(c.low)>0
        )
        if ranges:
            n=len(ranges)
            median_range=ranges[n//2] if n%2 else (ranges[n//2-1]+ranges[n//2])/2.0
        else:
            median_range=0.0
        return max(abs(float(level))*0.0008, median_range*0.10)

    @staticmethod
    def _breaks_recent(
        price: float,
        completed: Sequence[Any],
        bars: int,
        *,
        bullish: bool,
    ) -> bool:
        # Confirmed breakout: prior-window level + completed-candle close + live hold.
        rows=list(completed)
        if len(rows) < max(3, bars+1):
            return False

        reference=list(rows[-(bars+1):-1])
        confirm=rows[-1]
        if len(reference) < bars:
            return False

        level=(
            max(float(c.high) for c in reference)
            if bullish
            else min(float(c.low) for c in reference)
        )
        clearance=IntradayMovementEngine._breakout_clearance(level, reference)
        confirm_close=float(confirm.close)

        if bullish:
            close_confirmed=confirm_close >= level + clearance
            live_holding=float(price) >= level + clearance*0.25
        else:
            close_confirmed=confirm_close <= level - clearance
            live_holding=float(price) <= level - clearance*0.25

        return bool(close_confirmed and live_holding)

    @staticmethod
    def _structure_ratio(candles: Sequence[Any], direction: str) -> float:
        rows = list(candles)
        if len(rows) < 2:
            return 0.5
        aligned = 0
        total = 0
        for a, b in zip(rows, rows[1:]):
            if direction == "BULLISH":
                good = float(b.high) >= float(a.high) and float(b.low) >= float(a.low)
            else:
                good = float(b.high) <= float(a.high) and float(b.low) <= float(a.low)
            total += 1
            aligned += int(good)
        return aligned / max(1, total)

    @staticmethod
    def _structure_ratio_15m(bars: Sequence[tuple[float, float, float, float, int]], direction: str) -> float:
        if len(bars) < 2:
            return 0.5
        aligned = 0
        for a, b in zip(bars, bars[1:]):
            if direction == "BULLISH":
                good = b[1] >= a[1] and b[2] >= a[2]
            else:
                good = b[1] <= a[1] and b[2] <= a[2]
            aligned += int(good)
        return aligned / max(1, len(bars) - 1)

    @classmethod
    def _recent_relative_volume(
        cls,
        *,
        completed: Sequence[Any],
        grouped: Mapping[date, Sequence[Any]],
        current_date: date,
        window_bars: int,
    ) -> float:
        if len(completed) < window_bars:
            return 0.0
        current = sum(int(c.volume) for c in completed[-window_bars:])
        end_index = len(completed)
        samples: list[int] = []
        for session_date in sorted(grouped, reverse=True):
            if session_date >= current_date:
                continue
            session = list(grouped[session_date])
            if len(session) < end_index:
                continue
            start = max(0, end_index - window_bars)
            sample = sum(int(c.volume) for c in session[start:end_index])
            if sample > 0:
                samples.append(sample)
            if len(samples) >= 5:
                break
        baseline = median(samples) if samples else 0.0
        return current / baseline if baseline > 0 else 0.0

    @staticmethod
    def _trend_alignment_score(
        *, direction: str, price: float, vwap: float, ema9: float, ema20: float,
        ema50: float, ema9_15: float, ema20_15: float, adx: float,
        plus_di: float, minus_di: float, rsi: float, structure5: float,
        structure15: float, recent_rvol: float,
    ) -> float:
        bullish = direction == "BULLISH"
        score = 0.0
        if vwap > 0 and ((price > vwap) if bullish else (price < vwap)):
            score += 20.0
        if ema9 > 0 and ema20 > 0 and ((price > ema9 > ema20) if bullish else (price < ema9 < ema20)):
            score += 15.0
        elif ema20 > 0 and ((price > ema20) if bullish else (price < ema20)):
            score += 8.0
        if ema50 > 0 and ((price > ema50) if bullish else (price < ema50)):
            score += 7.0
        if ema9_15 > 0 and ema20_15 > 0 and ((ema9_15 >= ema20_15) if bullish else (ema9_15 <= ema20_15)):
            score += 8.0
        if adx >= 20:
            score += min(10.0, (adx - 15.0) / 2.0)
        if (plus_di > minus_di) if bullish else (minus_di > plus_di):
            score += 5.0
        if (52 <= rsi <= 78) if bullish else (22 <= rsi <= 48):
            score += 10.0
        score += max(0.0, min(1.0, structure5)) * 10.0
        score += max(0.0, min(1.0, structure15)) * 5.0
        score += min(10.0, max(0.0, recent_rvol - 1.0) / 2.0 * 10.0)
        return min(100.0, score)

    @staticmethod
    def _clean_trend_score(
        *, direction: str, price: float, vwap: float, ema20: float,
        pivot_state: str, range_position_percent: float,
        trend_retention_percent: float, structure5: float,
    ) -> float:
        bullish = direction == "BULLISH"
        score = 0.0
        if vwap > 0 and ((price > vwap) if bullish else (price < vwap)):
            score += 20.0
        edge = range_position_percent if bullish else 100.0 - range_position_percent
        score += max(0.0, min(20.0, (edge - 50.0) / 40.0 * 20.0))
        score += max(0.0, min(20.0, trend_retention_percent / 100.0 * 20.0))
        bullish_pivots = {"R1_TO_R2", "R2_TO_R3", "ABOVE_R3"}
        bearish_pivots = {"S2_TO_S1", "S3_TO_S2", "BELOW_S3"}
        if pivot_state in (bullish_pivots if bullish else bearish_pivots):
            score += 20.0
        elif pivot_state != "PIVOT_UNKNOWN":
            score += 8.0
        score += max(0.0, min(1.0, structure5)) * 10.0
        if ema20 > 0 and ((price > ema20) if bullish else (price < ema20)):
            score += 10.0
        return min(100.0, score)

    @staticmethod
    def _chase_risk_score(
        *, direction: str, pivot_state: str, rsi: float, extension_atr: float,
        vwap_distance_percent: float, recent15: float,
        range_position_percent: float, completed: Sequence[Any],
    ) -> float:
        bullish = direction == "BULLISH"
        score = 0.0
        if (bullish and pivot_state == "ABOVE_R3") or ((not bullish) and pivot_state == "BELOW_S3"):
            score += 25.0
        if (bullish and rsi >= 78) or ((not bullish) and rsi <= 22):
            score += 15.0
        if extension_atr > 2.5:
            score += min(20.0, (extension_atr - 2.5) / 2.5 * 20.0)
        if abs(vwap_distance_percent) > 2.5:
            score += min(15.0, (abs(vwap_distance_percent) - 2.5) / 2.5 * 15.0)
        directional_recent = recent15 if bullish else -recent15
        edge = range_position_percent if bullish else 100.0 - range_position_percent
        if directional_recent >= 1.5 and edge >= 97:
            score += 15.0
        rows = list(completed[-3:])
        if len(rows) == 3:
            same_direction = all((c.close > c.open) if bullish else (c.close < c.open) for c in rows)
            if same_direction:
                score += 10.0
        return min(100.0, score)

    @staticmethod
    def _median_true_range(candles: Sequence[Any]) -> float:
        rows = list(candles)
        if len(rows) < 2:
            return 0.0
        values: list[float] = []
        for i in range(1, len(rows)):
            current, previous = rows[i], rows[i - 1]
            values.append(max(
                float(current.high) - float(current.low),
                abs(float(current.high) - float(previous.close)),
                abs(float(current.low) - float(previous.close)),
            ))
        return median(values) if values else 0.0

    @staticmethod
    def _healthy_pullback(
        *, direction: str, price: float, vwap: float, ema20: float, atr: float,
        recent5: float, completed: Sequence[Any], previous_state: str,
    ) -> bool:
        if len(completed) < 3 or atr <= 0 or ema20 <= 0 or vwap <= 0:
            return False
        bullish = direction == "BULLISH"
        trend_side = (price >= ema20 and price >= vwap) if bullish else (price <= ema20 and price <= vwap)
        if not trend_side:
            return False
        recent_against = recent5 < 0 if bullish else recent5 > 0
        touched = any(
            min(abs(float(c.low) - ema20), abs(float(c.low) - vwap)) <= atr * 0.65
            if bullish
            else min(abs(float(c.high) - ema20), abs(float(c.high) - vwap)) <= atr * 0.65
            for c in completed[-3:]
        )
        established = bool(previous_state) and any(
            word in previous_state
            for word in ("TREND", "BREAKOUT", "BREAKDOWN", "EXTENDED", "PULLBACK", "ENTRY_READY")
        )
        return touched and (recent_against or established)

    # APLUS_BREAKOUT_CONFIRMATION_V1
    @staticmethod
    def _continuation_breakout(
        *,
        direction: str,
        price: float,
        recent5: float,
        completed: Sequence[Any],
        previous_state: str,
        healthy_pullback: bool,
    ) -> bool:
        rows=list(completed)
        if len(rows) < 4:
            return False

        bullish=direction=="BULLISH"
        resumes=recent5>0 if bullish else recent5<0
        prior_pullback=(
            healthy_pullback
            or "PULLBACK" in previous_state
            or "WAIT_FOR_PULLBACK" in previous_state
        )
        if not prior_pullback or not resumes:
            return False

        reference=list(rows[-3:-1])
        confirm=rows[-1]
        level=(
            max(float(c.high) for c in reference)
            if bullish
            else min(float(c.low) for c in reference)
        )
        clearance=IntradayMovementEngine._breakout_clearance(level, reference)
        confirm_close=float(confirm.close)

        if bullish:
            return (
                confirm_close >= level + clearance
                and float(price) >= level + clearance*0.25
            )
        return (
            confirm_close <= level - clearance
            and float(price) <= level - clearance*0.25
        )


__all__ = [
    "IntradayFeatures",
    "IntradayMovementEngine",
    "QuoteTape",
    "SessionStateStore",
    "TapeMetrics",
]
