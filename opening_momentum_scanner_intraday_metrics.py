"""
opening_momentum_scanner.py

Fast 09:15 opening-momentum discovery for NSE stock-option underlyings.

This module is intentionally separate from the slower full-universe option-chain
scanner. It uses one batch cash-market quote request for the complete F&O
universe, analyses five-minute candles only for a small quote shortlist, and
fetches option chains only for the strongest actionable candidates.

The scanner creates PAPER SIGNALS ONLY. It never places an order.
"""

from __future__ import annotations

import csv
import json
import math
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from analytics.enums import MarketBias, RecommendationType
from config import AppConfig
from core.dhan_client import DhanClient
from core.instrument_loader import InstrumentLoader, UnderlyingInstrument
from core.option_chain import OptionChainService
from logger import get_logger
from option_selector import OptionSelectionError, OptionSelector


logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")


@dataclass(slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def range(self) -> float:
        return max(0.0, self.high - self.low)

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open


@dataclass(slots=True)
class QuoteSnapshot:
    symbol: str
    security_id: str
    ltp: float
    open: float
    high: float
    low: float
    previous_close: float
    average_price: float
    volume: int
    net_change: float

    # Previous-session context. Kept separate from today's actual move.
    change_percent: float
    gap_percent: float

    # True intraday movement from the 09:15/day open.
    move_from_open_percent: float
    open_to_high_percent: float
    open_to_low_percent: float
    below_day_high_percent: float
    above_day_low_percent: float
    day_range_percent: float
    range_position: float
    range_position_percent: float
    trend_retention_percent: float
    move_type: str

    direction: str
    radar_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MomentumCandidate:
    symbol: str
    security_id: str
    direction: str
    stage: str
    score: float
    actionable: bool

    ltp: float
    previous_close: float
    day_open: float
    open_0915: float
    day_high: float
    day_low: float

    # Keep yesterday-close movement separate from true intraday movement.
    day_change_percent: float
    gap_percent: float
    move_from_open_percent: float
    move_from_0915_open_percent: float
    open_to_high_percent: float
    open_to_low_percent: float
    below_day_high_percent: float
    above_day_low_percent: float
    day_range_percent: float
    range_position: float
    range_position_percent: float
    trend_retention_percent: float
    move_type: str

    completed_5m_bars: int
    relative_volume: float
    vwap: float
    vwap_distance_percent: float
    atr_5m: float
    extension_atr: float

    first_candle_body_ratio: float
    aligned_structure_ratio: float
    opening_range_high: float
    opening_range_low: float
    opening_range_distance_percent: float
    opening_range_breakout: bool
    opening_direction_confirmed: bool

    underlying_entry: float
    underlying_stop: float
    underlying_target1: float
    underlying_target2: float
    underlying_target3: float
    underlying_risk_percent: float
    trailing_rule: str

    reasons: list[str] = field(default_factory=list)
    rejection_reason: str = ""
    option_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpeningMomentumScanner:
    """Find HAL/SONACOMS-style opening drives and select a liquid CE or PE."""

    def __init__(
        self,
        *,
        config: AppConfig,
        client: DhanClient,
        loader: InstrumentLoader,
        option_chain: OptionChainService,
        option_selector: OptionSelector | None = None,
    ) -> None:
        self.config = config
        self.settings = config.opening_momentum
        self.client = client
        self.loader = loader
        self.option_chain = option_chain
        self.option_selector = option_selector or OptionSelector()

        self._universe: list[UnderlyingInstrument] | None = None
        self._by_security_id: dict[str, UnderlyingInstrument] = {}
        self._option_cache: dict[str, tuple[float, dict[str, Any]]] = {}

        self.report_dir = Path(config.reports.output_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = Path(config.paths.data_dir) / "opening_momentum"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_once(
        self,
        *,
        force_refresh_instruments: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        started_monotonic = time.monotonic()
        current_time = self._as_ist(now or datetime.now(IST))
        phase = self._session_phase(current_time)

        universe = self._load_universe(
            force_refresh=force_refresh_instruments
        )
        quote_map = self.client.get_market_quotes(
            {"NSE_EQ": [item.security_id for item in universe]},
            mode="quote",
        )

        quotes, quote_errors = self._parse_quotes(
            universe=universe,
            quote_map=quote_map,
        )
        quote_shortlist = sorted(
            quotes,
            key=lambda item: item.radar_score,
            reverse=True,
        )[: self.settings.quote_shortlist_size]

        candle_shortlist = quote_shortlist[
            : self.settings.candle_shortlist_size
        ]
        history_by_symbol, history_errors = self._fetch_histories(
            candle_shortlist,
            current_time,
        )

        candidates: list[MomentumCandidate] = []
        for quote in candle_shortlist:
            candles = history_by_symbol.get(quote.symbol)
            if not candles:
                continue
            try:
                candidate = self._analyse_candidate(
                    quote=quote,
                    candles=candles,
                    now=current_time,
                )
            except Exception as exc:  # isolate a bad symbol
                history_errors[quote.symbol] = (
                    f"analysis {type(exc).__name__}: {exc}"
                )
                logger.exception(
                    "Opening-momentum analysis failed for %s",
                    quote.symbol,
                )
                continue
            candidates.append(candidate)

        candidates.sort(key=lambda item: item.score, reverse=True)
        actionable = [
            item
            for item in candidates
            if item.actionable
        ][: self.settings.maximum_option_candidates]

        trade_plans: list[dict[str, Any]] = []
        if self._new_entries_allowed(current_time):
            for candidate in actionable:
                underlying = self._by_security_id.get(
                    candidate.security_id
                )
                if underlying is None:
                    candidate.option_error = (
                        "Underlying instrument metadata is unavailable"
                    )
                    continue
                plan = self._build_option_plan(
                    candidate=candidate,
                    underlying=underlying,
                    now=current_time,
                )
                if plan is not None:
                    trade_plans.append(plan)

        elapsed = round(time.monotonic() - started_monotonic, 2)
        payload = {
            "generated_at": current_time.isoformat(),
            "mode": "PAPER_SIGNAL_ONLY",
            "live_orders_enabled": False,
            "session_phase": phase,
            "elapsed_seconds": elapsed,
            "universe": len(universe),
            "quotes_received": len(quotes),
            "quote_shortlist_size": len(quote_shortlist),
            "candles_analysed": len(candidates),
            "actionable_candidates": len(actionable),
            "option_trade_plans": len(trade_plans),
            "quote_shortlist": [
                item.to_dict()
                for item in quote_shortlist[
                    : self.settings.maximum_report_candidates
                ]
            ],
            "candidates": [
                item.to_dict()
                for item in candidates[
                    : self.settings.maximum_report_candidates
                ]
            ],
            "trade_plans": trade_plans,
            "errors": {
                **quote_errors,
                **history_errors,
            },
        }
        self._write_reports(payload)

        logger.info(
            "Opening momentum cycle complete phase=%s universe=%d "
            "quotes=%d analysed=%d actionable=%d option_plans=%d "
            "elapsed=%.2fs",
            phase,
            len(universe),
            len(quotes),
            len(candidates),
            len(actionable),
            len(trade_plans),
            elapsed,
        )
        return payload

    def run_loop(
        self,
        *,
        force_refresh_instruments: bool = False,
        poll_seconds: int | None = None,
    ) -> None:
        interval = max(
            10,
            int(poll_seconds or self.settings.poll_seconds),
        )
        first_run = True

        logger.info(
            "Opening Momentum Scanner started: %s-%s, poll=%ds, "
            "paper signals only",
            self.settings.session_start.strftime("%H:%M"),
            self.settings.session_stop.strftime("%H:%M"),
            interval,
        )

        while True:
            now = datetime.now(IST)
            phase = self._session_phase(now)

            if phase == "PRE_OPEN":
                seconds = self._seconds_until(
                    now,
                    self.settings.session_start,
                )
                sleep_for = max(1, min(30, seconds))
                logger.info(
                    "Waiting for opening session: %ds",
                    seconds,
                )
                time.sleep(sleep_for)
                continue

            if phase == "SESSION_COMPLETE":
                logger.info(
                    "Opening Momentum Scanner session complete for %s",
                    now.date().isoformat(),
                )
                return

            cycle_started = time.monotonic()
            self.run_once(
                force_refresh_instruments=(
                    force_refresh_instruments and first_run
                ),
                now=now,
            )
            first_run = False
            elapsed = time.monotonic() - cycle_started
            time.sleep(max(1.0, interval - elapsed))

    # ------------------------------------------------------------------
    # Universe and batch quote radar
    # ------------------------------------------------------------------

    def _load_universe(
        self,
        *,
        force_refresh: bool,
    ) -> list[UnderlyingInstrument]:
        if self._universe is None or force_refresh:
            self._universe = self.loader.load(
                force_refresh=force_refresh
            ).get_universe()
            self._by_security_id = {
                str(item.security_id): item
                for item in self._universe
            }
        return self._universe

    def _parse_quotes(
        self,
        *,
        universe: Sequence[UnderlyingInstrument],
        quote_map: Mapping[str, Any],
    ) -> tuple[list[QuoteSnapshot], dict[str, str]]:
        segment_data = quote_map.get("NSE_EQ", {})
        if not isinstance(segment_data, Mapping):
            segment_data = {}

        quotes: list[QuoteSnapshot] = []
        errors: dict[str, str] = {}

        for underlying in universe:
            security_id = str(underlying.security_id)
            raw = segment_data.get(security_id)
            if raw is None:
                raw = segment_data.get(int(security_id))
            if not isinstance(raw, Mapping):
                errors[underlying.symbol] = "market quote missing"
                continue

            try:
                quote = self._quote_snapshot(
                    underlying.symbol,
                    security_id,
                    raw,
                )
            except ValueError as exc:
                errors[underlying.symbol] = str(exc)
                continue

            if quote.ltp < self.settings.minimum_stock_price:
                continue
            if quote.volume < self.settings.minimum_cumulative_volume:
                continue
            # The opening radar is based on the actual move from today's
            # 09:15/day open. Previous-close change remains context only.
            if (
                abs(quote.move_from_open_percent)
                < self.settings.minimum_radar_move_percent
            ):
                continue
            quotes.append(quote)

        return quotes, errors

    def _quote_snapshot(
        self,
        symbol: str,
        security_id: str,
        raw: Mapping[str, Any],
    ) -> QuoteSnapshot:
        ohlc = raw.get("ohlc")
        if not isinstance(ohlc, Mapping):
            ohlc = {}

        ltp = self._positive(raw.get("last_price"))
        day_open = self._positive(ohlc.get("open"))
        day_high = self._positive(ohlc.get("high"))
        day_low = self._positive(ohlc.get("low"))
        previous_close = self._positive(ohlc.get("close"))

        if not all(
            value is not None
            for value in (
                ltp,
                day_open,
                day_high,
                day_low,
                previous_close,
            )
        ):
            raise ValueError("quote has invalid LTP/OHLC")

        assert ltp is not None
        assert day_open is not None
        assert day_high is not None
        assert day_low is not None
        assert previous_close is not None

        net_change = self._number(
            raw.get("net_change"),
            ltp - previous_close,
        )
        average_price = self._positive(raw.get("average_price"))
        if average_price is None:
            average_price = (day_high + day_low + ltp) / 3.0

        change_percent = (
            (ltp - previous_close) / previous_close * 100.0
        )
        gap_percent = (
            (day_open - previous_close) / previous_close * 100.0
        )
        move_from_open_percent = (
            (ltp - day_open) / day_open * 100.0
        )
        open_to_high_percent = (
            (day_high - day_open) / day_open * 100.0
        )
        open_to_low_percent = (
            (day_low - day_open) / day_open * 100.0
        )
        below_day_high_percent = (
            (day_high - ltp) / day_high * 100.0
        )
        above_day_low_percent = (
            (ltp - day_low) / day_low * 100.0
        )
        day_range_percent = (
            (day_high - day_low) / day_open * 100.0
        )
        range_position = self._range_position(
            ltp,
            day_low,
            day_high,
        )
        range_position_percent = range_position * 100.0
        trend_retention_percent = self._trend_retention_percent(
            ltp=ltp,
            day_open=day_open,
            day_high=day_high,
            day_low=day_low,
        )
        move_type = self._move_type(
            gap_percent=gap_percent,
            move_from_open_percent=move_from_open_percent,
        )

        direction, radar_score = self._radar_direction_score(
            change_percent=change_percent,
            gap_percent=gap_percent,
            move_from_open_percent=move_from_open_percent,
            day_range_percent=day_range_percent,
            range_position=range_position,
            trend_retention_percent=trend_retention_percent,
        )

        return QuoteSnapshot(
            symbol=str(symbol).strip().upper(),
            security_id=security_id,
            ltp=ltp,
            open=day_open,
            high=day_high,
            low=day_low,
            previous_close=previous_close,
            average_price=average_price,
            volume=max(0, int(self._number(raw.get("volume"), 0))),
            net_change=net_change,
            change_percent=change_percent,
            gap_percent=gap_percent,
            move_from_open_percent=move_from_open_percent,
            open_to_high_percent=open_to_high_percent,
            open_to_low_percent=open_to_low_percent,
            below_day_high_percent=below_day_high_percent,
            above_day_low_percent=above_day_low_percent,
            day_range_percent=day_range_percent,
            range_position=range_position,
            range_position_percent=range_position_percent,
            trend_retention_percent=trend_retention_percent,
            move_type=move_type,
            direction=direction,
            radar_score=round(radar_score, 2),
        )

    @staticmethod
    def _radar_direction_score(
        *,
        change_percent: float,
        gap_percent: float,
        move_from_open_percent: float,
        day_range_percent: float,
        range_position: float,
        trend_retention_percent: float,
    ) -> tuple[str, float]:
        """Rank the actual move since today's open, not merely the gap.

        The previous-close change is intentionally low weight. A stock that
        gaps up 4% but trades below its open should not outrank a genuine
        opening drive that is advancing from the 09:15 open.
        """
        retention = max(0.0, min(100.0, trend_retention_percent)) / 100.0

        bullish = (
            min(max(move_from_open_percent, 0.0) / 2.0, 1.0) * 45.0
            + range_position * 25.0
            + min(max(day_range_percent, 0.0) / 3.0, 1.0) * 15.0
            + retention * 10.0
            + min(max(change_percent, 0.0) / 4.0, 1.0) * 3.0
            + min(max(gap_percent, 0.0) / 4.0, 1.0) * 2.0
        )
        bearish = (
            min(max(-move_from_open_percent, 0.0) / 2.0, 1.0) * 45.0
            + (1.0 - range_position) * 25.0
            + min(max(day_range_percent, 0.0) / 3.0, 1.0) * 15.0
            + retention * 10.0
            + min(max(-change_percent, 0.0) / 4.0, 1.0) * 3.0
            + min(max(-gap_percent, 0.0) / 4.0, 1.0) * 2.0
        )
        if bullish >= bearish:
            return "BULLISH", min(100.0, bullish)
        return "BEARISH", min(100.0, bearish)

    # ------------------------------------------------------------------
    # Five-minute history and momentum scoring
    # ------------------------------------------------------------------

    def _fetch_histories(
        self,
        shortlist: Sequence[QuoteSnapshot],
        now: datetime,
    ) -> tuple[dict[str, list[Candle]], dict[str, str]]:
        if not shortlist:
            return {}, {}

        from_dt = datetime.combine(
            now.date() - timedelta(
                days=self.settings.history_calendar_days
            ),
            self.settings.session_start,
            tzinfo=IST,
        )
        to_dt = now + timedelta(minutes=1)

        histories: dict[str, list[Candle]] = {}
        errors: dict[str, str] = {}

        with ThreadPoolExecutor(
            max_workers=self.settings.historical_workers,
            thread_name_prefix="opening-history",
        ) as pool:
            future_map = {
                pool.submit(
                    self.client.get_intraday_candles,
                    security_id=quote.security_id,
                    segment="NSE_EQ",
                    instrument="EQUITY",
                    interval=5,
                    from_datetime=from_dt,
                    to_datetime=to_dt,
                    oi=False,
                ): quote
                for quote in shortlist
            }

            for future in as_completed(future_map):
                quote = future_map[future]
                try:
                    response = future.result()
                    candles = self._candles_from_response(response)
                    if not candles:
                        raise ValueError("historical API returned no candles")
                    histories[quote.symbol] = candles
                except Exception as exc:
                    errors[quote.symbol] = (
                        f"history {type(exc).__name__}: {exc}"
                    )

        return histories, errors

    def _candles_from_response(
        self,
        response: Mapping[str, Sequence[Any]],
    ) -> list[Candle]:
        timestamps = list(response.get("timestamp", []) or [])
        opens = list(response.get("open", []) or [])
        highs = list(response.get("high", []) or [])
        lows = list(response.get("low", []) or [])
        closes = list(response.get("close", []) or [])
        volumes = list(response.get("volume", []) or [])

        size = min(
            len(timestamps),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(volumes),
        )
        candles: list[Candle] = []

        for index in range(size):
            try:
                timestamp = datetime.fromtimestamp(
                    int(float(timestamps[index])),
                    IST,
                )
                candle = Candle(
                    timestamp=timestamp,
                    open=float(opens[index]),
                    high=float(highs[index]),
                    low=float(lows[index]),
                    close=float(closes[index]),
                    volume=max(0, int(float(volumes[index]))),
                )
            except (TypeError, ValueError, OverflowError, OSError):
                continue

            if (
                not all(
                    math.isfinite(value) and value > 0
                    for value in (
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                    )
                )
                or candle.high < candle.low
            ):
                continue
            candles.append(candle)

        candles.sort(key=lambda item: item.timestamp)
        return candles

    def _analyse_candidate(
        self,
        *,
        quote: QuoteSnapshot,
        candles: Sequence[Candle],
        now: datetime,
    ) -> MomentumCandidate:
        grouped = self._group_session_candles(candles)
        today = grouped.get(now.date(), [])
        completed = [
            candle
            for candle in today
            if candle.timestamp + timedelta(minutes=4, seconds=30) <= now
        ]

        if not completed:
            return self._rejected_candidate(
                quote,
                "WAITING_FOR_FIRST_COMPLETED_5M_CANDLE",
            )

        elapsed_slots = max(
            1,
            int(
                math.ceil(
                    max(
                        1.0,
                        (
                            datetime.combine(
                                now.date(),
                                now.time(),
                                tzinfo=IST,
                            )
                            - datetime.combine(
                                now.date(),
                                self.settings.session_start,
                                tzinfo=IST,
                            )
                        ).total_seconds()
                        / 300.0,
                    )
                )
            ),
        )
        relative_volume = self._relative_opening_volume(
            quote.volume,
            grouped,
            now.date(),
            elapsed_slots,
        )

        vwap = quote.average_price
        vwap_distance_percent = (
            (quote.ltp - vwap) / vwap * 100.0
            if vwap > 0
            else 0.0
        )
        aligned_vwap = (
            vwap_distance_percent > 0
            if quote.direction == "BULLISH"
            else vwap_distance_percent < 0
        )

        first = completed[0]
        open_0915 = first.open
        move_from_0915_open_percent = (
            (quote.ltp - open_0915) / open_0915 * 100.0
            if open_0915 > 0
            else quote.move_from_open_percent
        )
        first_body_ratio = (
            first.body / first.range
            if first.range > 0
            else 0.0
        )
        first_close_position = self._range_position(
            first.close,
            first.low,
            first.high,
        )
        first_alignment = (
            first.bullish
            if quote.direction == "BULLISH"
            else first.bearish
        )
        first_close_edge = (
            first_close_position
            if quote.direction == "BULLISH"
            else 1.0 - first_close_position
        )

        aligned_structure_ratio = self._structure_ratio(
            completed,
            quote.direction,
        )
        atr_5m = self._atr_proxy(grouped, now.date())
        extension_atr = (
            abs(quote.ltp - vwap) / atr_5m
            if atr_5m > 0
            else 0.0
        )

        opening_bars = completed[:3]
        opening_range_high = max(
            candle.high for candle in opening_bars
        )
        opening_range_low = min(
            candle.low for candle in opening_bars
        )
        buffer = (
            self.settings.opening_range_breakout_buffer_percent
            / 100.0
        )
        opening_range_distance_percent = (
            (quote.ltp - opening_range_high)
            / opening_range_high
            * 100.0
            if quote.direction == "BULLISH"
            else (
                (opening_range_low - quote.ltp)
                / opening_range_low
                * 100.0
            )
        )
        opening_range_breakout = (
            quote.ltp > opening_range_high * (1.0 + buffer)
            if quote.direction == "BULLISH"
            else quote.ltp < opening_range_low * (1.0 - buffer)
        )
        opening_direction_confirmed = self._opening_direction_confirmed(
            opening_bars,
            quote.direction,
        )

        score, score_reasons = self._momentum_score(
            quote=quote,
            relative_volume=relative_volume,
            first_body_ratio=first_body_ratio,
            first_close_edge=first_close_edge,
            first_alignment=first_alignment,
            aligned_structure_ratio=aligned_structure_ratio,
            aligned_vwap=aligned_vwap,
            opening_range_breakout=opening_range_breakout,
            opening_direction_confirmed=opening_direction_confirmed,
            extension_atr=extension_atr,
            vwap_distance_percent=vwap_distance_percent,
        )

        entry = quote.ltp
        stop, t1, t2, t3, risk_percent = self._risk_levels(
            direction=quote.direction,
            entry=entry,
            completed=completed,
        )

        stage, actionable, rejection = self._stage_and_actionability(
            now=now,
            direction=quote.direction,
            score=score,
            completed_bars=len(completed),
            first_alignment=first_alignment,
            first_body_ratio=first_body_ratio,
            aligned_vwap=aligned_vwap,
            relative_volume=relative_volume,
            opening_range_breakout=opening_range_breakout,
            opening_direction_confirmed=opening_direction_confirmed,
            extension_atr=extension_atr,
            vwap_distance_percent=vwap_distance_percent,
            risk_percent=risk_percent,
        )

        reasons = [
            (
                f"Radar {quote.radar_score:.1f}; previous-close "
                f"{quote.change_percent:+.2f}%; gap "
                f"{quote.gap_percent:+.2f}%; actual 09:15-open move "
                f"{move_from_0915_open_percent:+.2f}%"
            ),
            (
                f"Open {open_0915:.2f}; LTP {quote.ltp:.2f}; "
                f"high {quote.high:.2f}; low {quote.low:.2f}; "
                f"below high {quote.below_day_high_percent:.2f}%; "
                f"day-range position {quote.range_position_percent:.1f}%"
            ),
            (
                f"Relative opening volume {relative_volume:.2f}x; "
                f"VWAP distance {vwap_distance_percent:+.2f}%"
            ),
            (
                f"First 5m body ratio {first_body_ratio:.2f}; "
                f"aligned structure {aligned_structure_ratio:.2f}"
            ),
            (
                f"Opening range {opening_range_low:.2f}-"
                f"{opening_range_high:.2f}; directional distance "
                f"{opening_range_distance_percent:+.2f}%; breakout="
                f"{opening_range_breakout}; direction_confirmed="
                f"{opening_direction_confirmed}"
            ),
            *score_reasons,
        ]
        if rejection:
            reasons.append(f"No new entry: {rejection}")

        return MomentumCandidate(
            symbol=quote.symbol,
            security_id=quote.security_id,
            direction=quote.direction,
            stage=stage,
            score=round(score, 2),
            actionable=actionable,
            ltp=round(quote.ltp, 2),
            previous_close=round(quote.previous_close, 2),
            day_open=round(quote.open, 2),
            open_0915=round(open_0915, 2),
            day_high=round(quote.high, 2),
            day_low=round(quote.low, 2),
            day_change_percent=round(quote.change_percent, 3),
            gap_percent=round(quote.gap_percent, 3),
            move_from_open_percent=round(
                quote.move_from_open_percent,
                3,
            ),
            move_from_0915_open_percent=round(
                move_from_0915_open_percent,
                3,
            ),
            open_to_high_percent=round(
                quote.open_to_high_percent,
                3,
            ),
            open_to_low_percent=round(
                quote.open_to_low_percent,
                3,
            ),
            below_day_high_percent=round(
                quote.below_day_high_percent,
                3,
            ),
            above_day_low_percent=round(
                quote.above_day_low_percent,
                3,
            ),
            day_range_percent=round(
                quote.day_range_percent,
                3,
            ),
            range_position=round(quote.range_position, 3),
            range_position_percent=round(
                quote.range_position_percent,
                2,
            ),
            trend_retention_percent=round(
                quote.trend_retention_percent,
                2,
            ),
            move_type=quote.move_type,
            completed_5m_bars=len(completed),
            relative_volume=round(relative_volume, 3),
            vwap=round(vwap, 2),
            vwap_distance_percent=round(
                vwap_distance_percent,
                3,
            ),
            atr_5m=round(atr_5m, 3),
            extension_atr=round(extension_atr, 3),
            first_candle_body_ratio=round(first_body_ratio, 3),
            aligned_structure_ratio=round(
                aligned_structure_ratio,
                3,
            ),
            opening_range_high=round(opening_range_high, 2),
            opening_range_low=round(opening_range_low, 2),
            opening_range_distance_percent=round(
                opening_range_distance_percent,
                3,
            ),
            opening_range_breakout=opening_range_breakout,
            opening_direction_confirmed=(
                opening_direction_confirmed
            ),
            underlying_entry=round(entry, 2),
            underlying_stop=round(stop, 2),
            underlying_target1=round(t1, 2),
            underlying_target2=round(t2, 2),
            underlying_target3=round(t3, 2),
            underlying_risk_percent=round(risk_percent, 3),
            trailing_rule=(
                "For bullish trades, trail below the latest confirmed "
                "5-minute swing low or EMA20; for bearish trades, trail "
                "above the latest swing high or EMA20. No automatic order."
            ),
            reasons=reasons,
            rejection_reason=rejection,
        )

    def _momentum_score(
        self,
        *,
        quote: QuoteSnapshot,
        relative_volume: float,
        first_body_ratio: float,
        first_close_edge: float,
        first_alignment: bool,
        aligned_structure_ratio: float,
        aligned_vwap: bool,
        opening_range_breakout: bool,
        opening_direction_confirmed: bool,
        extension_atr: float,
        vwap_distance_percent: float,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        move_score = min(
            abs(quote.move_from_open_percent) / 2.0,
            1.0,
        ) * 27.0
        # Previous-close percentage is context, not the intraday signal.
        change_score = min(
            abs(quote.change_percent) / 4.0,
            1.0,
        ) * 3.0
        edge = (
            quote.range_position
            if quote.direction == "BULLISH"
            else 1.0 - quote.range_position
        )
        edge_score = max(0.0, min(1.0, edge)) * 10.0

        volume_score = max(
            0.0,
            min(
                1.0,
                (
                    relative_volume
                    - self.settings.minimum_relative_volume * 0.60
                )
                / max(
                    0.1,
                    self.settings.minimum_relative_volume * 1.20,
                ),
            ),
        ) * 18.0

        candle_score = (
            min(max(first_body_ratio, 0.0), 1.0) * 8.0
            + min(max(first_close_edge, 0.0), 1.0) * 5.0
        )
        if not first_alignment:
            candle_score *= 0.35

        structure_score = (
            min(max(aligned_structure_ratio, 0.0), 1.0)
            * 12.0
        )
        vwap_score = 10.0 if aligned_vwap else -12.0
        opening_score = (
            12.0
            if opening_range_breakout
            else 7.0
            if opening_direction_confirmed
            else 0.0
        )

        gap_alignment = (
            quote.change_percent > 0
            if quote.direction == "BULLISH"
            else quote.change_percent < 0
        )
        # Reward a gap only when today's open-to-LTP move follows through.
        gap_score = 2.0 if gap_alignment else 0.0

        score += (
            move_score
            + change_score
            + edge_score
            + volume_score
            + candle_score
            + structure_score
            + vwap_score
            + opening_score
            + gap_score
        )

        extension_penalty = 0.0
        if (
            extension_atr
            > self.settings.maximum_extension_atr
            or abs(vwap_distance_percent)
            > self.settings.maximum_extension_from_vwap_percent
        ):
            extension_penalty = min(
                25.0,
                10.0
                + max(
                    0.0,
                    extension_atr
                    - self.settings.maximum_extension_atr,
                )
                * 5.0,
            )
            score -= extension_penalty
            reasons.append(
                f"Extension penalty -{extension_penalty:.1f}"
            )

        reasons.append(
            "Components: "
            f"move={move_score:.1f}, change={change_score:.1f}, "
            f"range={edge_score:.1f}, volume={volume_score:.1f}, "
            f"candle={candle_score:.1f}, structure={structure_score:.1f}, "
            f"VWAP={vwap_score:.1f}, opening={opening_score:.1f}"
        )
        return max(0.0, min(100.0, score)), reasons

    def _stage_and_actionability(
        self,
        *,
        now: datetime,
        direction: str,
        score: float,
        completed_bars: int,
        first_alignment: bool,
        first_body_ratio: float,
        aligned_vwap: bool,
        relative_volume: float,
        opening_range_breakout: bool,
        opening_direction_confirmed: bool,
        extension_atr: float,
        vwap_distance_percent: float,
        risk_percent: float,
    ) -> tuple[str, bool, str]:
        prefix = "BULLISH" if direction == "BULLISH" else "BEARISH"

        if now.time() < self.settings.earliest_signal_time:
            return "WATCHING_OPEN", False, "earliest signal time not reached"

        if now.time() > self.settings.latest_entry_time:
            return f"{prefix}_TREND_NO_NEW_ENTRY", False, "entry window closed"

        if (
            extension_atr > self.settings.maximum_extension_atr
            or abs(vwap_distance_percent)
            > self.settings.maximum_extension_from_vwap_percent
        ):
            return "EXTENDED_NO_ENTRY", False, "price is too extended from VWAP"

        if risk_percent > self.settings.maximum_stop_percent:
            return "RISK_TOO_WIDE", False, "structural stop is too wide"

        if not first_alignment or first_body_ratio < 0.45:
            return "WEAK_OPENING_CANDLE", False, "opening candle quality is weak"

        if not aligned_vwap:
            return "VWAP_CONFLICT", False, "price is on the wrong side of VWAP"

        if relative_volume < self.settings.minimum_relative_volume:
            return "LOW_RELATIVE_VOLUME", False, "relative volume is insufficient"

        if now.time() < self.settings.confirmation_time:
            if (
                completed_bars >= 1
                and score >= self.settings.minimum_early_score
            ):
                return f"EARLY_{prefix}_MOMENTUM", True, ""
            return "EARLY_WATCHLIST", False, "early score below threshold"

        if (
            score >= self.settings.minimum_confirmed_score
            and opening_range_breakout
        ):
            return f"OPENING_{prefix}_BREAKOUT_CONFIRMED", True, ""

        if (
            score >= self.settings.minimum_confirmed_score
            and opening_direction_confirmed
        ):
            return f"OPENING_{prefix}_DIRECTION_CONFIRMED", True, ""

        return "MOMENTUM_WATCHLIST", False, "opening direction not confirmed"

    def _risk_levels(
        self,
        *,
        direction: str,
        entry: float,
        completed: Sequence[Candle],
    ) -> tuple[float, float, float, float, float]:
        recent = list(completed[-2:])
        buffer = self.settings.stop_buffer_percent / 100.0

        if direction == "BULLISH":
            # Use the latest completed candle as the primary opening-drive
            # structure. A two-bar minimum can become untradeably wide after
            # a strong first candle, exactly when continuation setups emerge.
            structural = recent[-1].low
            stop = structural * (1.0 - buffer)
            minimum_stop = entry * (
                1.0 - self.settings.minimum_stop_percent / 100.0
            )
            stop = min(stop, minimum_stop)
            risk = max(0.01, entry - stop)
            targets = (
                entry + risk,
                entry + risk * 2.0,
                entry + risk * 3.0,
            )
        else:
            structural = recent[-1].high
            stop = structural * (1.0 + buffer)
            minimum_stop = entry * (
                1.0 + self.settings.minimum_stop_percent / 100.0
            )
            stop = max(stop, minimum_stop)
            risk = max(0.01, stop - entry)
            targets = (
                max(0.01, entry - risk),
                max(0.01, entry - risk * 2.0),
                max(0.01, entry - risk * 3.0),
            )

        risk_percent = risk / entry * 100.0
        return stop, *targets, risk_percent

    # ------------------------------------------------------------------
    # Option selection
    # ------------------------------------------------------------------

    def _build_option_plan(
        self,
        *,
        candidate: MomentumCandidate,
        underlying: UnderlyingInstrument,
        now: datetime,
    ) -> dict[str, Any] | None:
        cached = self._cached_option(candidate.symbol)
        if cached is not None:
            option_contract = cached
        else:
            try:
                snapshot = self.option_chain.fetch(underlying)
                recommendation = (
                    RecommendationType.BUY
                    if candidate.direction == "BULLISH"
                    else RecommendationType.SELL
                )
                bias = (
                    MarketBias.BULLISH
                    if candidate.direction == "BULLISH"
                    else MarketBias.BEARISH
                )
                selected = self.option_selector.select(
                    snapshot=snapshot,
                    underlying=underlying,
                    recommendation=recommendation,
                    bias=bias,
                )
                option_contract = self._serializable(selected)
                self._option_cache[candidate.symbol] = (
                    time.monotonic(),
                    option_contract,
                )
            except OptionSelectionError as exc:
                candidate.option_error = str(exc)
                return None
            except Exception as exc:
                candidate.option_error = (
                    f"{type(exc).__name__}: {exc}"
                )
                logger.exception(
                    "Option selection failed for %s",
                    candidate.symbol,
                )
                return None

        return {
            "generated_at": now.isoformat(),
            "paper_signal_only": True,
            "symbol": candidate.symbol,
            "direction": candidate.direction,
            "stage": candidate.stage,
            "momentum_score": candidate.score,
            "underlying": {
                "entry": candidate.underlying_entry,
                "stop_loss": candidate.underlying_stop,
                "target1": candidate.underlying_target1,
                "target2": candidate.underlying_target2,
                "target3": candidate.underlying_target3,
                "risk_percent": candidate.underlying_risk_percent,
                "trailing_rule": candidate.trailing_rule,
            },
            "option_contract": option_contract,
            "reasons": candidate.reasons,
        }

    def _cached_option(
        self,
        symbol: str,
    ) -> dict[str, Any] | None:
        cached = self._option_cache.get(symbol)
        if cached is None:
            return None
        created_at, payload = cached
        if (
            time.monotonic() - created_at
            > self.settings.option_cache_seconds
        ):
            self._option_cache.pop(symbol, None)
            return None
        return payload

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _group_session_candles(
        self,
        candles: Sequence[Candle],
    ) -> dict[date, list[Candle]]:
        grouped: dict[date, list[Candle]] = {}
        for candle in candles:
            local = self._as_ist(candle.timestamp)
            if not (
                self.settings.session_start
                <= local.time()
                <= self.settings.market_close
            ):
                continue
            grouped.setdefault(local.date(), []).append(candle)

        for values in grouped.values():
            values.sort(key=lambda item: item.timestamp)
        return grouped

    def _relative_opening_volume(
        self,
        current_volume: int,
        grouped: Mapping[date, Sequence[Candle]],
        current_date: date,
        elapsed_slots: int,
    ) -> float:
        historical: list[int] = []
        for session_date, candles in grouped.items():
            if session_date >= current_date:
                continue
            sample = list(candles)[:elapsed_slots]
            if sample:
                total = sum(item.volume for item in sample)
                if total > 0:
                    historical.append(total)

        if not historical:
            return 1.0
        baseline = statistics.median(historical)
        return (
            current_volume / baseline
            if baseline > 0
            else 1.0
        )

    @staticmethod
    def _trend_retention_percent(
        *,
        ltp: float,
        day_open: float,
        day_high: float,
        day_low: float,
    ) -> float:
        """Percentage of today's maximum directional move still retained."""
        if ltp >= day_open:
            available = day_high - day_open
            retained = ltp - day_open
        else:
            available = day_open - day_low
            retained = day_open - ltp

        if available <= 0:
            return 0.0
        return max(0.0, min(100.0, retained / available * 100.0))

    @staticmethod
    def _move_type(
        *,
        gap_percent: float,
        move_from_open_percent: float,
    ) -> str:
        """Separate overnight gap from actual movement after 09:15."""
        gap_threshold = 0.50
        move_threshold = 0.40

        if gap_percent >= gap_threshold:
            if move_from_open_percent >= move_threshold:
                return "GAP_AND_GO_BULLISH"
            if move_from_open_percent <= -move_threshold:
                return "GAP_UP_FADE"
            return "GAP_UP_HOLDING"

        if gap_percent <= -gap_threshold:
            if move_from_open_percent <= -move_threshold:
                return "GAP_AND_GO_BEARISH"
            if move_from_open_percent >= move_threshold:
                return "GAP_DOWN_RECOVERY"
            return "GAP_DOWN_HOLDING"

        if move_from_open_percent >= move_threshold:
            return "OPENING_DRIVE_BULLISH"
        if move_from_open_percent <= -move_threshold:
            return "OPENING_DRIVE_BEARISH"
        return "INTRADAY_NEUTRAL"

    @staticmethod
    def _structure_ratio(
        candles: Sequence[Candle],
        direction: str,
    ) -> float:
        if len(candles) < 2:
            return 0.5

        aligned = 0
        comparisons = 0
        for previous, current in zip(candles, candles[1:]):
            comparisons += 2
            if direction == "BULLISH":
                aligned += int(current.high >= previous.high)
                aligned += int(current.low >= previous.low)
            else:
                aligned += int(current.high <= previous.high)
                aligned += int(current.low <= previous.low)

        return aligned / comparisons if comparisons else 0.5

    @staticmethod
    def _opening_direction_confirmed(
        opening_bars: Sequence[Candle],
        direction: str,
    ) -> bool:
        if len(opening_bars) < 3:
            return False

        first_open = opening_bars[0].open
        last_close = opening_bars[-1].close
        high = max(item.high for item in opening_bars)
        low = min(item.low for item in opening_bars)
        position = OpeningMomentumScanner._range_position(
            last_close,
            low,
            high,
        )

        if direction == "BULLISH":
            aligned_candles = sum(item.bullish for item in opening_bars)
            return (
                last_close > first_open
                and position >= 0.70
                and aligned_candles >= 2
            )

        aligned_candles = sum(item.bearish for item in opening_bars)
        return (
            last_close < first_open
            and position <= 0.30
            and aligned_candles >= 2
        )

    @staticmethod
    def _atr_proxy(
        grouped: Mapping[date, Sequence[Candle]],
        current_date: date,
    ) -> float:
        ranges: list[float] = []

        today = list(grouped.get(current_date, []))
        ranges.extend(item.range for item in today[-6:] if item.range > 0)

        for session_date in sorted(grouped, reverse=True):
            if session_date >= current_date:
                continue
            ranges.extend(
                item.range
                for item in list(grouped[session_date])[:6]
                if item.range > 0
            )
            if len(ranges) >= 24:
                break

        return statistics.median(ranges) if ranges else 0.0

    def _rejected_candidate(
        self,
        quote: QuoteSnapshot,
        reason: str,
    ) -> MomentumCandidate:
        return MomentumCandidate(
            symbol=quote.symbol,
            security_id=quote.security_id,
            direction=quote.direction,
            stage="WAITING_FOR_DATA",
            score=quote.radar_score,
            actionable=False,
            ltp=quote.ltp,
            previous_close=quote.previous_close,
            day_open=quote.open,
            day_high=quote.high,
            day_low=quote.low,
            day_change_percent=quote.change_percent,
            move_from_open_percent=quote.move_from_open_percent,
            range_position=quote.range_position,
            completed_5m_bars=0,
            relative_volume=0.0,
            vwap=quote.average_price,
            vwap_distance_percent=0.0,
            atr_5m=0.0,
            extension_atr=0.0,
            first_candle_body_ratio=0.0,
            aligned_structure_ratio=0.0,
            opening_range_high=0.0,
            opening_range_low=0.0,
            opening_range_breakout=False,
            opening_direction_confirmed=False,
            underlying_entry=quote.ltp,
            underlying_stop=0.0,
            underlying_target1=0.0,
            underlying_target2=0.0,
            underlying_target3=0.0,
            underlying_risk_percent=0.0,
            trailing_rule="",
            reasons=[reason],
            rejection_reason=reason,
        )

    def _session_phase(self, now: datetime) -> str:
        current = now.time()
        if current < self.settings.session_start:
            return "PRE_OPEN"
        if current < self.settings.earliest_signal_time:
            return "OPENING_OBSERVATION"
        if current < self.settings.confirmation_time:
            return "EARLY_MOMENTUM_DISCOVERY"
        if current <= self.settings.latest_entry_time:
            return "CONFIRMED_ENTRY_WINDOW"
        if current <= self.settings.session_stop:
            return "TREND_MONITORING_NO_NEW_ENTRIES"
        return "SESSION_COMPLETE"

    def _new_entries_allowed(self, now: datetime) -> bool:
        return (
            self.settings.earliest_signal_time
            <= now.time()
            <= self.settings.latest_entry_time
        )

    @staticmethod
    def _seconds_until(now: datetime, clock: Any) -> int:
        target = datetime.combine(now.date(), clock, tzinfo=IST)
        return max(0, int((target - now).total_seconds()))

    def _write_reports(self, payload: Mapping[str, Any]) -> None:
        latest_json = self.report_dir / "opening_momentum_latest.json"
        timestamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        archive_json = (
            self.report_dir
            / f"opening_momentum_{timestamp}.json"
        )
        csv_path = self.report_dir / "opening_momentum_candidates.csv"

        self._atomic_json(latest_json, payload)
        self._atomic_json(archive_json, payload)

        candidates = list(payload.get("candidates", []) or [])
        fields = [
            "symbol",
            "direction",
            "stage",
            "score",
            "actionable",
            "move_type",
            "previous_close",
            "day_change_percent",
            "gap_percent",
            "day_open",
            "open_0915",
            "ltp",
            "move_from_open_percent",
            "move_from_0915_open_percent",
            "day_high",
            "open_to_high_percent",
            "below_day_high_percent",
            "day_low",
            "open_to_low_percent",
            "above_day_low_percent",
            "day_range_percent",
            "range_position_percent",
            "trend_retention_percent",
            "relative_volume",
            "vwap",
            "vwap_distance_percent",
            "completed_5m_bars",
            "opening_range_high",
            "opening_range_low",
            "opening_range_distance_percent",
            "opening_range_breakout",
            "opening_direction_confirmed",
            "underlying_entry",
            "underlying_stop",
            "underlying_risk_percent",
            "rejection_reason",
            "option_error",
        ]

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = csv_path.with_suffix(".csv.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for candidate in candidates:
                writer.writerow(
                    {
                        key: candidate.get(key, "")
                        for key in fields
                    }
                )
        os.replace(temporary, csv_path)

    @staticmethod
    def _atomic_json(
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=path.name,
            suffix=".tmp",
            dir=path.parent,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(
                json.dumps(
                    OpeningMomentumScanner._serializable(payload),
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _serializable(value: Any) -> Any:
        if is_dataclass(value):
            return OpeningMomentumScanner._serializable(asdict(value))
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Mapping):
            return {
                str(key): OpeningMomentumScanner._serializable(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [
                OpeningMomentumScanner._serializable(item)
                for item in value
            ]
        return value

    @staticmethod
    def _range_position(
        price: float,
        low: float,
        high: float,
    ) -> float:
        spread = high - low
        if spread <= 0:
            return 0.5
        return max(0.0, min(1.0, (price - low) / spread))

    @staticmethod
    def _positive(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        return number

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _as_ist(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=IST)
        return value.astimezone(IST)


__all__ = [
    "Candle",
    "MomentumCandidate",
    "OpeningMomentumScanner",
    "QuoteSnapshot",
]
