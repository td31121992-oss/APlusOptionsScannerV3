"""
opening_momentum_scanner.py

Continuous 09:15-15:30 intraday movement discovery for NSE stock-option underlyings.

This module continuously watches the full F&O cash-market universe with one batch
quote request, maintains a lightweight quote tape to detect fresh 5/10/15/30-minute
acceleration, analyses detailed 5m/15m candles only for a dynamic shortlist, and
fetches option chains only for the strongest actionable candidates.

The scanner creates PAPER SIGNALS ONLY. It never places an order.
"""

from __future__ import annotations
from open_move_pattern_observer import observe_open_move_patterns
from leadership_v6_live_shadow import LeadershipV6Shadow

import csv
import json
import logging
import math
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, time as clock_time, timedelta
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
from intraday_movement_engine import IntradayMovementEngine, TapeMetrics
from option_selector import OptionSelectionError, OptionSelector
from paper_trade_journal import PaperTradeJournal
from safety_gate import SafetyGateEngine


logger = get_logger(__name__)
from stock_selection_v2 import V2GateConfig, evaluate_entry_ready, rank_raw_movers

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

    recent_move_5m_percent: float = 0.0
    recent_move_10m_percent: float = 0.0
    recent_move_15m_percent: float = 0.0
    recent_move_30m_percent: float = 0.0
    tape_volume_acceleration_5m: float = 1.0
    tape_volume_acceleration_15m: float = 1.0
    direction_source: str = "SESSION_FROM_OPEN"

    direction: str = "BULLISH"
    radar_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MomentumCandidate:
    symbol: str
    security_id: str
    direction: str
    stage: str
    score: float
    trade_quality_score: float
    movement_capture_score: float
    shortlist: str
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
    trend_alignment_score: float = 0.0
    clean_trend_score: float = 0.0
    chase_risk_score: float = 0.0
    setup_family: str = "TREND_MONITORING"
    selection_tier: str = "WATCH"
    previous_state: str = ""

    first_candle_body_ratio: float = 0.0
    aligned_structure_ratio: float = 0.0
    opening_range_high: float = 0.0
    opening_range_low: float = 0.0
    opening_range_distance_percent: float = 0.0
    opening_range_breakout: bool = False
    opening_direction_confirmed: bool = False

    underlying_entry: float = 0.0
    underlying_stop: float = 0.0
    underlying_target1: float = 0.0
    underlying_target2: float = 0.0
    underlying_target3: float = 0.0
    underlying_risk_percent: float = 0.0
    trailing_rule: str = ""

    reasons: list[str] = field(default_factory=list)
    rejection_reason: str = ""
    option_error: str = ""
    safety_decision: str = ""
    safety_block_reasons: list[str] = field(default_factory=list)
    safety_warnings: list[str] = field(default_factory=list)
    paper_trade_id: str = ""
    paper_trade_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


logger = logging.getLogger(__name__)


class OpeningMomentumScanner:
    """Stateful all-day F&O movement engine; legacy class name kept for compatibility."""

    def __init__(
        self,
        *,
        config: AppConfig,
        client: DhanClient,
        loader: InstrumentLoader,
        option_chain: OptionChainService,
        option_selector: OptionSelector | None = None,
        safety_gate: SafetyGateEngine | None = None,
    ) -> None:
        self.config = config
        self.settings = config.opening_momentum
        self.client = client
        self.loader = loader
        self.option_chain = option_chain
        self.option_selector = option_selector or OptionSelector()
        self.safety_gate = safety_gate or SafetyGateEngine.from_env(
            data_dir=config.paths.data_dir
        )
        # APLUS_PAPER_CIRCUIT_BREAKER_WIRING_V1
        self.paper_portfolio_state_path = (
            Path(config.paths.data_dir) / "portfolio_state.json"
        )
        self.paper_state_max_age_seconds = max(
            10,
            int(os.getenv("APLUS_PAPER_STATE_MAX_AGE_SECONDS", "60")),
        )

        self._universe: list[UnderlyingInstrument] | None = None
        self._by_security_id: dict[str, UnderlyingInstrument] = {}
        self._option_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._account_cache: dict[str, tuple[float, Any]] = {}
        self._fund_cache_seconds = max(
            30,
            int(os.getenv("INTRADAY_ACCOUNT_FUND_CACHE_SECONDS", "300")),
        )
        self._positions_cache_seconds = max(
            5,
            int(os.getenv("INTRADAY_ACCOUNT_POSITIONS_CACHE_SECONDS", "30")),
        )

        self.report_dir = Path(config.reports.output_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.leadership_v6_shadow = LeadershipV6Shadow(self.report_dir)
        self.state_dir = Path(config.paths.data_dir) / "opening_momentum"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.intraday_state_dir = Path(config.paths.data_dir) / "intraday_movement"
        self.intraday_state_dir.mkdir(parents=True, exist_ok=True)
        self.intraday_engine = IntradayMovementEngine(
            state_dir=self.intraday_state_dir,
            settings=self.settings,
        )
        self.paper_journal = PaperTradeJournal(
            state_dir=self.intraday_state_dir,
            report_dir=self.report_dir,
            rearm_minutes=int(getattr(
                self.settings, "paper_trade_rearm_minutes", 20
            )),
        )

    # APLUS_PAPER_CIRCUIT_BREAKER_WIRING_V1
    def _paper_native_circuit_breaker(
        self,
        now: datetime,
    ) -> dict[str, Any]:
        path = self.paper_portfolio_state_path
        result: dict[str, Any] = {
            "enabled": True,
            "blocked": False,
            "decision": "PASS",
            "reasons": [],
            "state_path": str(path),
            "state_valid": False,
            "state_age_seconds": None,
            "consecutive_losses": 0,
            "maximum_consecutive_losses": int(
                self.safety_gate.config.maximum_consecutive_losses
            ),
            "realized_pnl_today": 0.0,
            "maximum_daily_loss": 0.0,
        }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("portfolio state is not a JSON object")
        except Exception as exc:
            result["blocked"] = True
            result["decision"] = "BLOCK"
            result["reasons"].append(
                f"PAPER_STATE_MISSING_OR_INVALID: {type(exc).__name__}: {exc}"
            )
            return result

        mode = str(payload.get("mode") or "").strip().upper()
        state_date = str(payload.get("date") or "").strip()
        as_of_raw = str(payload.get("as_of") or "").strip()
        if mode != "PAPER_NATIVE":
            result["reasons"].append(
                f"PAPER_STATE_MODE_INVALID: expected PAPER_NATIVE got {mode or 'EMPTY'}"
            )
        if state_date != now.date().isoformat():
            result["reasons"].append(
                f"PAPER_STATE_DATE_MISMATCH: expected {now.date().isoformat()} got {state_date or 'EMPTY'}"
            )
        try:
            as_of = datetime.fromisoformat(as_of_raw)
            as_of = self._as_ist(as_of)
            age_seconds = max(0.0, (now - as_of).total_seconds())
            result["state_age_seconds"] = round(age_seconds, 2)
            if age_seconds > self.paper_state_max_age_seconds:
                result["reasons"].append(
                    "PAPER_STATE_STALE: "
                    f"age={age_seconds:.1f}s limit={self.paper_state_max_age_seconds}s"
                )
        except Exception:
            result["reasons"].append("PAPER_STATE_AS_OF_INVALID")

        consecutive_losses = int(float(payload.get("consecutive_losses") or 0))
        realized_pnl = float(payload.get("realized_pnl_today") or 0.0)
        result["consecutive_losses"] = consecutive_losses
        result["realized_pnl_today"] = round(realized_pnl, 2)

        cfg = self.safety_gate.config
        max_losses = int(cfg.maximum_consecutive_losses)
        if max_losses > 0 and consecutive_losses >= max_losses:
            result["reasons"].append(
                "CONSECUTIVE_LOSS_LIMIT: "
                f"consecutive_losses={consecutive_losses} limit={max_losses}"
            )

        capital = float(payload.get("capital_override") or 0.0)
        if capital <= 0:
            capital = float(cfg.fallback_account_capital)
        max_daily_loss = capital * float(cfg.maximum_daily_loss_percent) / 100.0
        result["maximum_daily_loss"] = round(max_daily_loss, 2)
        if realized_pnl <= -max_daily_loss:
            result["reasons"].append(
                "DAILY_LOSS_LIMIT: "
                f"realized_pnl={realized_pnl:.2f} limit=-{max_daily_loss:.2f}"
            )

        result["state_valid"] = not any(
            str(x).startswith("PAPER_STATE_") for x in result["reasons"]
        )
        if result["reasons"]:
            result["blocked"] = True
            result["decision"] = "BLOCK"
        return result

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
        # APLUS_SHARED_QUOTE_SCHEDULER_V3_1
        open_paper_positions = self.paper_journal.open_positions(current_time)
        open_option_ids = sorted({
            str(item.get("option_security_id") or "")
            for item in open_paper_positions
            if str(item.get("option_security_id") or "")
        })
        quote_request = {"NSE_EQ": [item.security_id for item in universe]}
        if open_option_ids:
            quote_request["NSE_FNO"] = open_option_ids
        quote_map = self.client.get_market_quotes(quote_request, mode="quote")

        # Stock Selection V2: rank the full F&O universe by actual movement
        # from today's market open. Top-5 UP are CE-eligible; Top-5 DOWN are
        # PE-eligible. Membership is dynamic on every scanner cycle.
        v2_movers = rank_raw_movers(
            universe=universe,
            quote_map=quote_map,
            top_n=5,
        )
        v2_mover_symbols = set(v2_movers.get("symbols", []) or [])

        quotes, quote_errors = self._parse_quotes(
            universe=universe,
            quote_map=quote_map,
            now=current_time,
            forced_symbols=v2_mover_symbols,
        )
        missing_quote_symbols = sorted(
            symbol for symbol, error in quote_errors.items()
            if error == "market quote missing"
        )
        invalid_quote_symbols = sorted(
            symbol for symbol, error in quote_errors.items()
            if error != "market quote missing"
        )
        raw_quotes_received = max(
            0,
            len(universe) - len(missing_quote_symbols) - len(invalid_quote_symbols),
        )

        # Full F&O market watch from the SAME 208-stock quote response.
        # This adds ZERO additional Dhan API requests.
        fno_market_watch = self._build_fno_market_watch(
            universe=universe,
            quote_map=quote_map,
            now=current_time,
        )

        # APLUS_SHARED_QUOTE_SCHEDULER_V3_1
        paper_position_update = self._monitor_paper_positions_from_quote_map(
            now=current_time,
            quote_map=quote_map,
            positions=open_paper_positions,
            force_close=False,
        )

        radar_ranked = sorted(
            quotes,
            key=lambda item: item.radar_score,
            reverse=True,
        )
        quote_by_symbol = {item.symbol: item for item in quotes}
        v2_priority_quotes = [
            quote_by_symbol[symbol]
            for symbol in v2_movers.get("symbols", [])
            if symbol in quote_by_symbol
        ]
        seen_v2 = {item.symbol for item in v2_priority_quotes}
        merged_quotes = v2_priority_quotes + [
            item for item in radar_ranked if item.symbol not in seen_v2
        ]
        quote_shortlist = merged_quotes[
            : max(10, self.settings.quote_shortlist_size)
        ]
        candle_shortlist = quote_shortlist[
            : max(10, self.settings.candle_shortlist_size)
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
            except Exception as exc:
                history_errors[quote.symbol] = (
                    f"analysis {type(exc).__name__}: {exc}"
                )
                logger.exception(
                    "Intraday movement analysis failed for %s",
                    quote.symbol,
                )
                continue
            candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                item.actionable,
                item.trade_quality_score,
                item.trend_alignment_score,
                item.movement_capture_score,
            ),
            reverse=True,
        )
        (
            entry_ready,
            strong_trend_wait_for_pullback,
            fresh_movement,
            near_misses,
        ) = self._build_shortlists(candidates)

        leadership_shadow_rows = self.leadership_v6_shadow.evaluate(candidates, current_time)
        leadership_shadow_hits = [
            x for x in leadership_shadow_rows
            if x.get("qualified_shadow")
        ]
        if leadership_shadow_hits:
            logger.info(
                "LEADERSHIP_V6_SHADOW hits=%d symbols=%s",
                len(leadership_shadow_hits),
                ",".join(
                    str(x.get("symbol"))
                    for x in leadership_shadow_hits[:10]
                ),
            )


        # A+ selective gate: quality first; daily limit is only a safety ceiling.
        selective_entry_ready = [
            item for item in entry_ready
            if self._aplus_selective_entry_allowed(item)
        ]
        selective_gate_rejected = [
            item for item in entry_ready
            if item not in selective_entry_ready
        ]

        # APLUS_SELECTIVE_GATE_DIAGNOSTIC_V1
        selective_rejection_counts: dict[str, int] = {}
        for _c in selective_gate_rejected:
            _r = str(_c.paper_trade_status or "A_PLUS_REJECT_UNSPECIFIED")
            selective_rejection_counts[_r] = selective_rejection_counts.get(_r, 0) + 1
        if entry_ready:
            logger.info(
                "APLUS_SELECTIVE_GATE_AUDIT entry_ready=%d selective_pass=%d selective_reject=%d reasons=%s passed_symbols=%s rejected_symbols=%s",
                len(entry_ready), len(selective_entry_ready), len(selective_gate_rejected),
                "|".join(f"{k}:{v}" for k,v in sorted(selective_rejection_counts.items(), key=lambda kv:(-kv[1],kv[0]))) or "NONE",
                ",".join(x.symbol for x in selective_entry_ready[:10]) or "NONE",
                ",".join(f"{x.symbol}:{x.paper_trade_status or 'UNKNOWN'}" for x in selective_gate_rejected[:10]) or "NONE",
            )

        # Quality-first: trade count is an outcome, never a quota.
        actionable = selective_entry_ready
        v2_config = V2GateConfig()
        actionable, v2_blocked = evaluate_entry_ready(
            candidates=actionable,
            mover_ranking=v2_movers,
            now=current_time,
            config=v2_config,
        )
        for blocked in v2_blocked:
            candidate = next(
                (
                    x for x in entry_ready
                    if x.symbol == blocked.get("symbol")
                    and x.direction == blocked.get("direction")
                ),
                None,
            )
            if candidate is not None:
                candidate.paper_trade_status = "V2_STOCK_SELECTION_BLOCKED"
                candidate.reasons.append(
                    "Stock Selection V2 blocked: "
                    + "; ".join(blocked.get("reasons", []) or [])
                )

        movement_leaders = sorted(
            candidates,
            key=lambda item: (
                item.movement_capture_score,
                item.trend_alignment_score,
                item.trade_quality_score,
            ),
            reverse=True,
        )

        trade_plans: list[dict[str, Any]] = []
        safety_evaluations: list[dict[str, Any]] = []
        account_context: dict[str, Any] = {
            "fund_limits": {},
            "positions": [],
            "fund_limits_fetch_ok": False,
            "positions_fetch_ok": False,
            "errors": [],
        }
        duplicate_paper_signals_suppressed = 0

        # APLUS_PAPER_CIRCUIT_BREAKER_WIRING_V1
        paper_circuit_breaker = self._paper_native_circuit_breaker(current_time)
        actionable_for_plans = list(actionable)
        if paper_circuit_breaker.get("blocked") and actionable_for_plans:
            reasons = list(paper_circuit_breaker.get("reasons") or [])
            for candidate in actionable_for_plans:
                candidate.safety_decision = "BLOCK"
                candidate.safety_block_reasons = [
                    "PAPER_CIRCUIT_BREAKER: " + reason for reason in reasons
                ]
                candidate.paper_trade_status = "SAFETY_BLOCKED"
                candidate.option_error = (
                    "SAFETY_BLOCKED: PAPER_CIRCUIT_BREAKER: " + "; ".join(reasons)
                )
                safety_evaluations.append({
                    "symbol": candidate.symbol,
                    "evaluated_at": current_time.isoformat(),
                    "mode": "PAPER_NATIVE",
                    "allowed": False,
                    "decision": "BLOCK",
                    "checks": [{
                        "name": "PAPER_CIRCUIT_BREAKER",
                        "status": "BLOCK",
                        "message": "; ".join(reasons),
                        "details": dict(paper_circuit_breaker),
                    }],
                    "block_reasons": [
                        "PAPER_CIRCUIT_BREAKER: " + reason for reason in reasons
                    ],
                    "warnings": [],
                })
                logger.warning(
                    "PAPER_SAFETY_BLOCK symbol=%s direction=%s reasons=%s "
                    "consecutive_losses=%s limit=%s realized_pnl=%.2f",
                    candidate.symbol,
                    candidate.direction,
                    "|".join(reasons),
                    paper_circuit_breaker.get("consecutive_losses"),
                    paper_circuit_breaker.get("maximum_consecutive_losses"),
                    float(paper_circuit_breaker.get("realized_pnl_today") or 0.0),
                )
            actionable_for_plans = []

        if self._new_entries_allowed(current_time) and actionable_for_plans:
            account_context = self._load_account_safety_context()
            for candidate in actionable_for_plans:
                if not self.paper_journal.can_generate(
                    symbol=candidate.symbol,
                    direction=candidate.direction,
                    when=current_time,
                ):
                    candidate.paper_trade_status = (
                        "ALREADY_JOURNALED_WAITING_FOR_SETUP_RESET"
                    )
                    duplicate_paper_signals_suppressed += 1
                    continue

                underlying = self._by_security_id.get(candidate.security_id)
                if underlying is None:
                    candidate.option_error = (
                        "Underlying instrument metadata is unavailable"
                    )
                    candidate.paper_trade_status = "OPTION_PLAN_FAILED"
                    continue
                plan = self._build_option_plan(
                    candidate=candidate,
                    underlying=underlying,
                    now=current_time,
                    account_context=account_context,
                    safety_evaluations=safety_evaluations,
                )
                logger.info(
                    'PAPER conversion audit symbol=%s direction=%s plan=%s safety=%s option_error=%s',
                    candidate.symbol,
                    candidate.direction,
                    'PASS' if plan is not None else 'FAIL',
                    candidate.safety_decision or '',
                    candidate.option_error or '',
                )
                if plan is not None:
                    record = self.paper_journal.record_trade(
                        plan=plan,
                        candidate=candidate.to_dict(),
                        when=current_time,
                    )
                    trade_id = str(record.get("paper_trade_id") or "")
                    candidate.paper_trade_id = trade_id
                    candidate.paper_trade_status = "OPEN"
                    plan["paper_trade_id"] = trade_id
                    plan["paper_trade_status"] = "OPEN"
                    trade_plans.append(plan)
                else:
                    candidate.paper_trade_status = (
                        "SAFETY_BLOCKED"
                        if candidate.option_error.startswith("SAFETY_BLOCKED:")
                        else "OPTION_PLAN_FAILED"
                    )

        # Re-arm a symbol/direction only after its setup becomes non-actionable.
        # If a candidate drops out of the analysed shortlist, the journal also
        # re-arms it after paper_trade_rearm_minutes.
        for candidate in candidates:
            self.paper_journal.observe_candidate(
                symbol=candidate.symbol,
                direction=candidate.direction,
                stage=candidate.stage,
                actionable=candidate.actionable,
                when=current_time,
            )

        # Persist the full-universe tape, state machine and paper-trade journal.
        self.intraday_engine.flush()
        self.paper_journal.flush()
        paper_journal_summary = self.paper_journal.summary(current_time)

        elapsed = round(time.monotonic() - started_monotonic, 2)
        payload = {
            "generated_at": current_time.isoformat(),
            "mode": "PAPER_SIGNAL_ONLY",
            "live_orders_enabled": False,
            "scanner_mode": "CONTINUOUS_INTRADAY_MOVEMENT",
            "monitoring_window": "09:15-15:30 IST",
            "paper_trade_window": (
                "09:15-15:30 IST; quality-gated with no intraday clock cutoff"
            ),
            "safety_mode": self.safety_gate.config.mode,
            "paper_native_circuit_breaker": paper_circuit_breaker,
            "session_phase": phase,
            "elapsed_seconds": elapsed,
            "universe": len(universe),
            "raw_quotes_received": raw_quotes_received,
            "fno_market_watch": fno_market_watch,
            "radar_qualified_quotes": len(quotes),
            "missing_quote_count": len(missing_quote_symbols),
            "missing_quote_symbols": missing_quote_symbols,
            "invalid_quote_count": len(invalid_quote_symbols),
            "invalid_quote_symbols": invalid_quote_symbols,
            # Backward-compatible field retained.
            "quotes_received": len(quotes),
            "quote_shortlist_size": len(quote_shortlist),
            "candles_analysed": len(candidates),
            "actionable_candidates": len(actionable),
            "aplus_selective_gate": {
                "entry_ready_before_selective": len(entry_ready),
                "passed_selective": len(selective_entry_ready),
                "rejected_selective": len(selective_gate_rejected),
                "rejection_counts": dict(selective_rejection_counts),
                "rejected_symbols": [
                    {"symbol":x.symbol,"direction":x.direction,"status":x.paper_trade_status,
                     "trade_quality_score":x.trade_quality_score,
                     "trend_alignment_score":x.trend_alignment_score,
                     "clean_trend_score":x.clean_trend_score,
                     "relative_volume":x.relative_volume,
                     "recent_relative_volume_15m":x.recent_relative_volume_15m,
                     "tape_volume_acceleration_5m":x.tape_volume_acceleration_5m,
                     "tape_volume_acceleration_15m":x.tape_volume_acceleration_15m,
                     "recent_move_10m_percent":x.recent_move_10m_percent,
                     "vwap_distance_percent":x.vwap_distance_percent}
                    for x in selective_gate_rejected
                ],
            },
            "stock_selection_v2": {
                "enabled": True,
                "rule": (
                    "Dynamic Top-5 UP -> CE / Top-5 DOWN -> PE; "
                    "then require fresh continuation, participation and retention"
                ),
                "top_n_per_side": v2_config.top_n_per_side,
                "top_up": list(v2_movers.get("top_up", []) or []),
                "top_down": list(v2_movers.get("top_down", []) or []),
                "eligible_symbols": list(v2_movers.get("symbols", []) or []),
                "entry_ready_before_v2": len(entry_ready),
                "passed_v2": len(actionable),
                "passed_symbols": [
                    {
                        "symbol": x.symbol,
                        "direction": x.direction,
                        "setup_family": x.setup_family,
                        "move_from_0915_open_pct": x.move_from_0915_open_percent,
                        "recent_5m_pct": x.recent_move_5m_percent,
                        "recent_10m_pct": x.recent_move_10m_percent,
                        "recent_15m_pct": x.recent_move_15m_percent,
                    }
                    for x in actionable
                ],
                "blocked_count": len(v2_blocked),
                "blocked": v2_blocked,
            },
            "entry_ready_count": len(entry_ready),
            "early_entry_candidates_count": len(entry_ready),
            "fresh_movement_count": len(fresh_movement),
            "strong_trend_wait_for_pullback_count": len(strong_trend_wait_for_pullback),
            "near_misses_count": len(near_misses),
            "option_trade_plans": len(trade_plans),
            "new_paper_trades_this_cycle": len(trade_plans),
            "paper_trades_today": int(
                paper_journal_summary.get("paper_trades_today") or 0
            ),
            "duplicate_paper_signals_suppressed": (
                duplicate_paper_signals_suppressed
            ),
            "paper_trade_journal": paper_journal_summary,
            "paper_positions_closed_this_cycle": len(paper_position_update.get("closed", [])),
            "paper_position_quote_errors": list(paper_position_update.get("errors", [])),
            "safety_evaluations_count": len(safety_evaluations),
            "safety_blocked_count": sum(
                1 for item in safety_evaluations
                if item.get("decision") == "BLOCK"
            ),
            "account_safety_context": {
                "fund_limits_fetch_ok": bool(account_context.get("fund_limits_fetch_ok")),
                "positions_fetch_ok": bool(account_context.get("positions_fetch_ok")),
                "positions_received": len(account_context.get("positions", []) or []),
                "errors": list(account_context.get("errors", []) or []),
            },
            "safety_gate_evaluations": safety_evaluations,
            "shortlists": {
                "ENTRY_READY": [item.to_dict() for item in entry_ready],
                # Legacy key intentionally aliases the all-day entry-ready list.
                "EARLY_ENTRY_CANDIDATES": [item.to_dict() for item in entry_ready],
                "FRESH_MOVEMENT": [item.to_dict() for item in fresh_movement],
                "STRONG_TREND_WAIT_FOR_PULLBACK": [
                    item.to_dict() for item in strong_trend_wait_for_pullback
                ],
                "NEAR_MISSES": [item.to_dict() for item in near_misses],
            },
            "movement_leaders": [
                item.to_dict()
                for item in movement_leaders[: self.settings.maximum_report_candidates]
            ],
            "quote_shortlist": [
                item.to_dict()
                for item in quote_shortlist[: self.settings.maximum_report_candidates]
            ],
            "candidates": [
                item.to_dict()
                for item in candidates[: self.settings.maximum_report_candidates]
            ],
            "trade_plans": trade_plans,
            "errors": {**quote_errors, **history_errors},
        }
        # OPEN_MOVE_PATTERN_OBSERVER_V1
        # Observation only; never changes actionability, trade gates, risk or option selection.
        try:
            payload["open_move_pattern_observer"] = observe_open_move_patterns(
                payload=payload,
                current_time=current_time,
                report_dir=self.report_dir,
                logger=logger,
            )
        except Exception as exc:
            logger.warning(
                "OPEN_MOVE_PATTERN_OBSERVER cycle failed non-fatally: %s: %s",
                type(exc).__name__,
                exc,
            )

        self._write_reports(payload)

        logger.info(
            "Intraday movement cycle phase=%s universe=%d raw_quotes=%d "
            "radar=%d analysed=%d entry_ready=%d fresh=%d wait=%d "
            "plans=%d paper_today=%d open=%d closed=%d net_pnl=%.2f "
            "dup_suppressed=%d safety_blocked=%d elapsed=%.2fs",
            phase, len(universe), raw_quotes_received, len(quotes),
            len(candidates), len(entry_ready), len(fresh_movement),
            len(strong_trend_wait_for_pullback), len(trade_plans),
            int(paper_journal_summary.get("paper_trades_today") or 0),
            int(paper_journal_summary.get("open_positions") or 0),
            int(paper_journal_summary.get("closed_trades") or 0),
            float(paper_journal_summary.get("net_pnl") or 0.0),
            duplicate_paper_signals_suppressed,
            sum(1 for item in safety_evaluations if item.get("decision") == "BLOCK"),
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
            "Continuous Intraday Movement Scanner started: %s-%s, poll=%ds, "
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
                    "Waiting for intraday monitoring session: %ds",
                    seconds,
                )
                time.sleep(sleep_for)
                continue

            if phase == "SESSION_COMPLETE":
                final_update = self._monitor_paper_positions(now=now, force_close=True)
                self.paper_journal.flush()
                final_summary = self.paper_journal.summary(now)
                logger.info(
                    "Continuous Intraday Movement Scanner session complete for %s "
                    "paper=%d open=%d closed=%d net_pnl=%.2f final_closed=%d",
                    now.date().isoformat(),
                    int(final_summary.get("paper_trades_today") or 0),
                    int(final_summary.get("open_positions") or 0),
                    int(final_summary.get("closed_trades") or 0),
                    float(final_summary.get("net_pnl") or 0.0),
                    len(final_update.get("closed", [])),
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

    # APLUS_SHARED_QUOTE_SCHEDULER_V3_1
    def _monitor_paper_positions_from_quote_map(
        self,
        *,
        now: datetime,
        quote_map: Mapping[str, Any],
        positions: list[Mapping[str, Any]] | None,
        force_close: bool,
    ) -> dict[str, Any]:
        active = list(positions or [])
        if not active:
            return {"closed": [], "errors": [], "quote_source": "SHARED_MAIN_QUOTE"}
        ids = sorted({
            str(item.get("option_security_id") or "")
            for item in active
            if str(item.get("option_security_id") or "")
        })
        if not ids:
            return {"closed": [], "errors": ["open paper positions have no option security_id"], "quote_source": "SHARED_MAIN_QUOTE"}
        segment = quote_map.get("NSE_FNO", {}) if isinstance(quote_map, Mapping) else {}
        if not isinstance(segment, Mapping):
            segment = {}
        missing = [security_id for security_id in ids if security_id not in segment]
        if missing:
            logger.warning(
                "APLUS_SHARED_QUOTE_SCHEDULER_V3_1 missing_option_quotes=%d ids=%s; next normal cycle will retry",
                len(missing), ",".join(missing[:10]),
            )
        try:
            closed = self.paper_journal.update_open_positions(
                option_quotes=segment,
                when=now,
                force_close=force_close,
                force_close_reason="SESSION_END",
            )
            return {
                "closed": closed,
                "errors": ([f"shared quote missing option ids: {','.join(missing)}"] if missing else []),
                "quote_source": "SHARED_MAIN_QUOTE",
                "requested_option_ids": len(ids),
                "received_option_quotes": sum(1 for security_id in ids if security_id in segment),
            }
        except Exception as exc:
            logger.warning("PAPER shared-position update failed: %s: %s", type(exc).__name__, exc)
            return {"closed": [], "errors": [f"{type(exc).__name__}: {exc}"], "quote_source": "SHARED_MAIN_QUOTE"}

    def _monitor_paper_positions(self, *, now: datetime, force_close: bool) -> dict[str, Any]:
        """Fetch option LTPs for OPEN PAPER positions and update their lifecycle."""
        positions = self.paper_journal.open_positions(now)
        if not positions:
            return {"closed": [], "errors": []}
        ids = sorted({str(x.get("option_security_id") or "") for x in positions if str(x.get("option_security_id") or "")})
        if not ids:
            return {"closed": [], "errors": ["open paper positions have no option security_id"]}
        try:
            quote_map = self.client.get_market_quotes({"NSE_FNO": ids}, mode="quote")
            segment = quote_map.get("NSE_FNO", {})
            if not isinstance(segment, Mapping):
                segment = {}
            closed = self.paper_journal.update_open_positions(
                option_quotes=segment, when=now, force_close=force_close,
                force_close_reason="SESSION_END",
            )
            return {"closed": closed, "errors": []}
        except Exception as exc:
            logger.warning("PAPER position quote refresh failed: %s: %s", type(exc).__name__, exc)
            return {"closed": [], "errors": [f"{type(exc).__name__}: {exc}"]}

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

    def _build_fno_market_watch(
        self,
        *,
        universe: Sequence[UnderlyingInstrument],
        quote_map: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """Build full F&O market watch from the SAME quote batch used by scanner."""
        segment_data = quote_map.get("NSE_EQ", {})
        if not isinstance(segment_data, Mapping):
            segment_data = {}

        sector_map: dict[str, str] = {}
        sector_file = Path(self.config.paths.data_dir) / "reference" / "fno_sector_map.csv"
        if sector_file.is_file():
            try:
                with sector_file.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        symbol = str(row.get("symbol") or "").strip().upper()
                        sector = str(row.get("sector") or "").strip()
                        if symbol and sector:
                            sector_map[symbol] = sector
            except Exception:
                sector_map = {}

        rows: list[dict[str, Any]] = []
        for underlying in universe:
            security_id = str(underlying.security_id)
            raw = segment_data.get(security_id)
            if raw is None:
                try:
                    raw = segment_data.get(int(security_id))
                except (TypeError, ValueError):
                    raw = None
            if not isinstance(raw, Mapping):
                continue

            ohlc = raw.get("ohlc")
            if not isinstance(ohlc, Mapping):
                ohlc = {}

            ltp = self._positive(raw.get("last_price"))
            day_open = self._positive(ohlc.get("open"))
            day_high = self._positive(ohlc.get("high"))
            day_low = self._positive(ohlc.get("low"))
            previous_close = self._positive(ohlc.get("close"))
            if not all(v is not None for v in (ltp, day_open, day_high, day_low, previous_close)):
                continue

            assert ltp is not None
            assert day_open is not None
            assert day_high is not None
            assert day_low is not None
            assert previous_close is not None

            from_open = (ltp - day_open) / day_open * 100.0
            from_prev = (ltp - previous_close) / previous_close * 100.0
            gap_pct = (day_open - previous_close) / previous_close * 100.0
            range_pos = self._range_position(ltp, day_low, day_high) * 100.0
            symbol = str(underlying.symbol).strip().upper()

            rows.append({
                "symbol": symbol,
                "security_id": security_id,
                "sector": sector_map.get(symbol, "UNCLASSIFIED"),
                "open_0915": round(day_open, 2),
                "ltp": round(ltp, 2),
                "previous_close": round(previous_close, 2),
                "gap_pct": round(gap_pct, 3),
                "from_open_pct": round(from_open, 3),
                "from_prev_close_pct": round(from_prev, 3),
                "day_high": round(day_high, 2),
                "day_low": round(day_low, 2),
                "range_position_pct": round(range_pos, 2),
                "direction": "UP" if from_open > 0 else "DOWN" if from_open < 0 else "FLAT",
            })

        rows.sort(key=lambda x: x["from_open_pct"], reverse=True)
        sectors: dict[str, dict[str, Any]] = {}
        for row in rows:
            sec = row["sector"]
            item = sectors.setdefault(sec, {"sector": sec, "stocks": 0, "advancing": 0, "declining": 0, "sum_move": 0.0})
            item["stocks"] += 1
            item["advancing"] += int(row["from_open_pct"] > 0)
            item["declining"] += int(row["from_open_pct"] < 0)
            item["sum_move"] += float(row["from_open_pct"])

        sector_rows = []
        for item in sectors.values():
            count = max(1, int(item["stocks"]))
            sector_rows.append({
                "sector": item["sector"],
                "stocks": item["stocks"],
                "advancing": item["advancing"],
                "declining": item["declining"],
                "average_from_open_pct": round(item["sum_move"] / count, 3),
            })
        sector_rows.sort(key=lambda x: x["average_from_open_pct"], reverse=True)
        return {"generated_at": now.isoformat(), "count": len(rows), "rows": rows, "sectors": sector_rows}

    def _parse_quotes(
        self,
        *,
        universe: Sequence[UnderlyingInstrument],
        quote_map: Mapping[str, Any],
        now: datetime,
        forced_symbols: set[str] | None = None,
    ) -> tuple[list[QuoteSnapshot], dict[str, str]]:
        segment_data = quote_map.get("NSE_EQ", {})
        if not isinstance(segment_data, Mapping):
            segment_data = {}

        quotes: list[QuoteSnapshot] = []
        errors: dict[str, str] = {}
        forced_symbols = {
            str(x).strip().upper()
            for x in (forced_symbols or set())
            if str(x).strip()
        }

        for underlying in universe:
            security_id = str(underlying.security_id)
            raw = segment_data.get(security_id)
            if raw is None:
                try:
                    raw = segment_data.get(int(security_id))
                except (TypeError, ValueError):
                    raw = None
            if not isinstance(raw, Mapping):
                errors[underlying.symbol] = "market quote missing"
                continue

            try:
                quote = self._quote_snapshot(
                    underlying.symbol,
                    security_id,
                    raw,
                    now=now,
                )
            except ValueError as exc:
                errors[underlying.symbol] = str(exc)
                continue

            if quote.ltp < self.settings.minimum_stock_price:
                continue
            if quote.volume < self.settings.minimum_cumulative_volume:
                continue

            # A full-day radar must admit both established session movers and
            # stocks that have only just accelerated during the last 5-30 min.
            movement_trigger = max(
                abs(quote.move_from_open_percent),
                abs(quote.recent_move_5m_percent) * 1.25,
                abs(quote.recent_move_10m_percent) * 1.15,
                abs(quote.recent_move_15m_percent),
                abs(quote.recent_move_30m_percent) * 0.85,
            )
            volume_wakeup = max(
                quote.tape_volume_acceleration_5m,
                quote.tape_volume_acceleration_15m,
            ) >= float(getattr(
                self.settings,
                "minimum_recent_volume_acceleration",
                1.30,
            ))
            if (
                movement_trigger < self.settings.minimum_radar_move_percent
                and not volume_wakeup
                and str(underlying.symbol).strip().upper() not in forced_symbols
            ):
                continue
            quotes.append(quote)

        return quotes, errors

    def _quote_snapshot(
        self,
        symbol: str,
        security_id: str,
        raw: Mapping[str, Any],
        *,
        now: datetime,
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
            for value in (ltp, day_open, day_high, day_low, previous_close)
        ):
            raise ValueError("quote has invalid LTP/OHLC")

        assert ltp is not None
        assert day_open is not None
        assert day_high is not None
        assert day_low is not None
        assert previous_close is not None

        net_change = self._number(raw.get("net_change"), ltp - previous_close)
        average_price = self._positive(raw.get("average_price"))
        if average_price is None:
            average_price = (day_high + day_low + ltp) / 3.0
        volume = max(0, int(self._number(raw.get("volume"), 0)))

        change_percent = (ltp - previous_close) / previous_close * 100.0
        gap_percent = (day_open - previous_close) / previous_close * 100.0
        move_from_open_percent = (ltp - day_open) / day_open * 100.0
        open_to_high_percent = (day_high - day_open) / day_open * 100.0
        open_to_low_percent = (day_low - day_open) / day_open * 100.0
        below_day_high_percent = (day_high - ltp) / day_high * 100.0
        above_day_low_percent = (ltp - day_low) / day_low * 100.0
        day_range_percent = (day_high - day_low) / day_open * 100.0
        range_position = self._range_position(ltp, day_low, day_high)
        range_position_percent = range_position * 100.0
        trend_retention_percent = self._trend_retention_percent(
            ltp=ltp, day_open=day_open, day_high=day_high, day_low=day_low
        )
        move_type = self._move_type(
            gap_percent=gap_percent,
            move_from_open_percent=move_from_open_percent,
        )

        tape = self.intraday_engine.observe_quote(
            symbol=str(symbol).strip().upper(),
            when=now,
            ltp=ltp,
            volume=volume,
        )
        direction, radar_score, direction_source = self._radar_direction_score(
            change_percent=change_percent,
            gap_percent=gap_percent,
            move_from_open_percent=move_from_open_percent,
            day_range_percent=day_range_percent,
            range_position=range_position,
            trend_retention_percent=trend_retention_percent,
            recent_move_5m_percent=tape.move_5m_percent,
            recent_move_10m_percent=tape.move_10m_percent,
            recent_move_15m_percent=tape.move_15m_percent,
            recent_move_30m_percent=tape.move_30m_percent,
            volume_acceleration_5m=tape.volume_acceleration_5m,
            volume_acceleration_15m=tape.volume_acceleration_15m,
        )

        return QuoteSnapshot(
            symbol=str(symbol).strip().upper(),
            security_id=security_id,
            ltp=ltp, open=day_open, high=day_high, low=day_low,
            previous_close=previous_close, average_price=average_price,
            volume=volume, net_change=net_change,
            change_percent=change_percent, gap_percent=gap_percent,
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
            recent_move_5m_percent=tape.move_5m_percent,
            recent_move_10m_percent=tape.move_10m_percent,
            recent_move_15m_percent=tape.move_15m_percent,
            recent_move_30m_percent=tape.move_30m_percent,
            tape_volume_acceleration_5m=tape.volume_acceleration_5m,
            tape_volume_acceleration_15m=tape.volume_acceleration_15m,
            direction_source=direction_source,
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
        recent_move_5m_percent: float = 0.0,
        recent_move_10m_percent: float = 0.0,
        recent_move_15m_percent: float = 0.0,
        recent_move_30m_percent: float = 0.0,
        volume_acceleration_5m: float = 1.0,
        volume_acceleration_15m: float = 1.0,
    ) -> tuple[str, float, str]:
        """Rank both session movement and fresh all-day acceleration."""
        retention = max(0.0, min(100.0, trend_retention_percent)) / 100.0
        recent_candidates = [
            recent_move_5m_percent * 1.35,
            recent_move_10m_percent * 1.20,
            recent_move_15m_percent,
            recent_move_30m_percent * 0.80,
        ]
        recent = max(recent_candidates, key=lambda x: abs(x))
        use_recent = abs(recent) >= max(0.30, abs(move_from_open_percent) * 0.45)
        directional_anchor = recent if use_recent else move_from_open_percent
        direction_source = "RECENT_ACCELERATION" if use_recent else "SESSION_FROM_OPEN"

        volume_bonus = min(12.0, max(0.0, max(
            volume_acceleration_5m, volume_acceleration_15m
        ) - 1.0) * 4.0)
        session_strength = min(abs(move_from_open_percent) / 2.5, 1.0) * 28.0
        recent_strength = min(abs(recent) / 1.25, 1.0) * 28.0
        range_strength = min(max(day_range_percent, 0.0) / 3.0, 1.0) * 10.0
        context_change = min(abs(change_percent) / 4.0, 1.0) * 3.0
        context_gap = min(abs(gap_percent) / 4.0, 1.0) * 2.0

        if directional_anchor >= 0:
            edge = range_position * 17.0
            direction = "BULLISH"
        else:
            edge = (1.0 - range_position) * 17.0
            direction = "BEARISH"

        score = (
            session_strength + recent_strength + range_strength + edge
            + retention * 10.0 + context_change + context_gap + volume_bonus
        )
        return direction, min(100.0, score), direction_source

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
                quote, "WAITING_FOR_FIRST_COMPLETED_5M_CANDLE"
            )

        elapsed_slots = max(
            1,
            int(math.ceil(max(
                1.0,
                (
                    datetime.combine(now.date(), now.time(), tzinfo=IST)
                    - datetime.combine(
                        now.date(), self.settings.session_start, tzinfo=IST
                    )
                ).total_seconds() / 300.0,
            ))),
        )
        relative_volume = self._relative_opening_volume(
            quote.volume, grouped, now.date(), elapsed_slots
        )

        vwap = quote.average_price
        vwap_distance_percent = (
            (quote.ltp - vwap) / vwap * 100.0 if vwap > 0 else 0.0
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
            if open_0915 > 0 else quote.move_from_open_percent
        )
        first_body_ratio = first.body / first.range if first.range > 0 else 0.0
        first_close_position = self._range_position(
            first.close, first.low, first.high
        )
        first_alignment = first.bullish if quote.direction == "BULLISH" else first.bearish
        first_close_edge = (
            first_close_position if quote.direction == "BULLISH"
            else 1.0 - first_close_position
        )

        aligned_structure_ratio = self._structure_ratio(
            completed, quote.direction
        )
        atr_5m = self._atr_proxy(grouped, now.date())
        extension_atr = abs(quote.ltp - vwap) / atr_5m if atr_5m > 0 else 0.0

        opening_bars = completed[:3]
        opening_range_high = max(candle.high for candle in opening_bars)
        opening_range_low = min(candle.low for candle in opening_bars)
        buffer = self.settings.opening_range_breakout_buffer_percent / 100.0
        opening_range_distance_percent = (
            (quote.ltp - opening_range_high) / opening_range_high * 100.0
            if quote.direction == "BULLISH"
            else (opening_range_low - quote.ltp) / opening_range_low * 100.0
        )
        opening_range_breakout = (
            quote.ltp > opening_range_high * (1.0 + buffer)
            if quote.direction == "BULLISH"
            else quote.ltp < opening_range_low * (1.0 - buffer)
        )
        opening_direction_confirmed = self._opening_direction_confirmed(
            opening_bars, quote.direction
        )

        features = self.intraday_engine.analyse(
            symbol=quote.symbol,
            direction=quote.direction,
            price=quote.ltp,
            vwap=vwap,
            completed=completed,
            grouped=grouped,
            current_date=now.date(),
            now=now,
            range_position_percent=quote.range_position_percent,
            trend_retention_percent=quote.trend_retention_percent,
            extension_atr=extension_atr,
            vwap_distance_percent=vwap_distance_percent,
            tape_metrics=TapeMetrics(
                move_5m_percent=quote.recent_move_5m_percent,
                move_10m_percent=quote.recent_move_10m_percent,
                move_15m_percent=quote.recent_move_15m_percent,
                move_30m_percent=quote.recent_move_30m_percent,
                volume_acceleration_5m=quote.tape_volume_acceleration_5m,
                volume_acceleration_15m=quote.tape_volume_acceleration_15m,
            ),
        )

        effective_relative_volume = max(
            relative_volume,
            features.recent_relative_volume_15m,
            features.tape_volume_acceleration_5m,
            features.tape_volume_acceleration_15m,
        )
        score, score_reasons = self._momentum_score(
            quote=quote,
            relative_volume=effective_relative_volume,
            first_body_ratio=first_body_ratio,
            first_close_edge=first_close_edge,
            first_alignment=first_alignment,
            aligned_structure_ratio=max(
                aligned_structure_ratio, features.five_minute_structure_ratio
            ),
            aligned_vwap=aligned_vwap,
            opening_range_breakout=opening_range_breakout,
            opening_direction_confirmed=opening_direction_confirmed,
            extension_atr=extension_atr,
            vwap_distance_percent=vwap_distance_percent,
        )
        # Later-session entries should be able to score strongly from current
        # 5m/15m structure even when the first 09:15 candle was mediocre.
        if now.time() > getattr(self.settings, "opening_phase_end", self.settings.confirmation_time):
            score = max(
                score,
                features.trend_alignment_score * 0.72
                + features.clean_trend_score * 0.28,
            )

        movement_capture_score = self._movement_capture_score(
            direction=quote.direction,
            move_from_0915_open_percent=move_from_0915_open_percent,
            relative_volume=effective_relative_volume,
            trend_retention_percent=quote.trend_retention_percent,
            range_position=quote.range_position,
            opening_range_distance_percent=opening_range_distance_percent,
        )
        directional_recent15 = (
            features.recent_move_15m_percent
            if quote.direction == "BULLISH"
            else -features.recent_move_15m_percent
        )
        recent_capture = (
            min(max(directional_recent15, 0.0) / 1.50, 1.0) * 35.0
            + min(max(effective_relative_volume - 1.0, 0.0) / 3.0, 1.0) * 20.0
            + features.trend_alignment_score * 0.25
            + features.clean_trend_score * 0.20
        )
        movement_capture_score = max(
            movement_capture_score, min(100.0, recent_capture)
        )

        entry = quote.ltp
        stop, t1, t2, t3, risk_percent = self._risk_levels(
            direction=quote.direction, entry=entry, completed=completed
        )

        stage, actionable, rejection = self._stage_and_actionability(
            now=now,
            direction=quote.direction,
            score=score,
            completed_bars=len(completed),
            first_alignment=first_alignment,
            first_body_ratio=first_body_ratio,
            aligned_vwap=aligned_vwap,
            relative_volume=effective_relative_volume,
            opening_range_breakout=opening_range_breakout,
            opening_direction_confirmed=opening_direction_confirmed,
            extension_atr=extension_atr,
            vwap_distance_percent=vwap_distance_percent,
            risk_percent=risk_percent,
            features=features.to_dict(),
        )

        reasons = [
            (
                f"Radar {quote.radar_score:.1f} via {quote.direction_source}; "
                f"previous-close {quote.change_percent:+.2f}%; gap "
                f"{quote.gap_percent:+.2f}%; 09:15-open move "
                f"{move_from_0915_open_percent:+.2f}%"
            ),
            (
                f"Recent moves 5m {features.recent_move_5m_percent:+.2f}%, "
                f"10m {features.recent_move_10m_percent:+.2f}%, "
                f"15m {features.recent_move_15m_percent:+.2f}%, "
                f"30m {features.recent_move_30m_percent:+.2f}%"
            ),
            (
                f"Session RVOL {relative_volume:.2f}x; recent 15m RVOL "
                f"{features.recent_relative_volume_15m:.2f}x; tape volume "
                f"acceleration 5m {features.tape_volume_acceleration_5m:.2f}x / "
                f"15m {features.tape_volume_acceleration_15m:.2f}x"
            ),
            (
                f"VWAP {vwap:.2f} ({vwap_distance_percent:+.2f}%); "
                f"EMA9/20/50 {features.ema9_5m:.2f}/"
                f"{features.ema20_5m:.2f}/{features.ema50_5m:.2f}; "
                f"15m EMA9/20 {features.ema9_15m:.2f}/{features.ema20_15m:.2f}"
            ),
            (
                f"ADX {features.adx14_5m:.1f}; +DI {features.plus_di_5m:.1f}; "
                f"-DI {features.minus_di_5m:.1f}; RSI {features.rsi14_5m:.1f}; "
                f"pivot_state={features.pivot_state}"
            ),
            (
                f"Setup {features.setup_family}; tier {features.selection_tier}; "
                f"alignment {features.trend_alignment_score:.1f}; clean trend "
                f"{features.clean_trend_score:.1f}; chase risk "
                f"{features.chase_risk_score:.1f}"
            ),
            (
                f"Trade quality {score:.2f}; movement capture "
                f"{movement_capture_score:.2f}; previous state "
                f"{features.previous_state or '-'}"
            ),
            *score_reasons,
        ]
        if rejection:
            reasons.append(f"No new entry: {rejection}")

        candidate = MomentumCandidate(
            symbol=quote.symbol, security_id=quote.security_id,
            direction=quote.direction, stage=stage,
            score=round(score, 2), trade_quality_score=round(score, 2),
            movement_capture_score=round(movement_capture_score, 2),
            shortlist="", actionable=actionable, ltp=round(quote.ltp, 2),
            previous_close=round(quote.previous_close, 2),
            day_open=round(quote.open, 2), open_0915=round(open_0915, 2),
            day_high=round(quote.high, 2), day_low=round(quote.low, 2),
            day_change_percent=round(quote.change_percent, 3),
            gap_percent=round(quote.gap_percent, 3),
            move_from_open_percent=round(quote.move_from_open_percent, 3),
            move_from_0915_open_percent=round(move_from_0915_open_percent, 3),
            open_to_high_percent=round(quote.open_to_high_percent, 3),
            open_to_low_percent=round(quote.open_to_low_percent, 3),
            below_day_high_percent=round(quote.below_day_high_percent, 3),
            above_day_low_percent=round(quote.above_day_low_percent, 3),
            day_range_percent=round(quote.day_range_percent, 3),
            range_position=round(quote.range_position, 3),
            range_position_percent=round(quote.range_position_percent, 2),
            trend_retention_percent=round(quote.trend_retention_percent, 2),
            move_type=quote.move_type, completed_5m_bars=len(completed),
            relative_volume=round(relative_volume, 3),
            vwap=round(vwap, 2),
            vwap_distance_percent=round(vwap_distance_percent, 3),
            atr_5m=round(atr_5m, 3), extension_atr=round(extension_atr, 3),
            recent_move_5m_percent=round(features.recent_move_5m_percent, 3),
            recent_move_10m_percent=round(features.recent_move_10m_percent, 3),
            recent_move_15m_percent=round(features.recent_move_15m_percent, 3),
            recent_move_30m_percent=round(features.recent_move_30m_percent, 3),
            tape_volume_acceleration_5m=round(features.tape_volume_acceleration_5m, 3),
            tape_volume_acceleration_15m=round(features.tape_volume_acceleration_15m, 3),
            recent_relative_volume_15m=round(features.recent_relative_volume_15m, 3),
            ema9_5m=round(features.ema9_5m, 2),
            ema20_5m=round(features.ema20_5m, 2),
            ema50_5m=round(features.ema50_5m, 2),
            ema9_15m=round(features.ema9_15m, 2),
            ema20_15m=round(features.ema20_15m, 2),
            rsi14_5m=round(features.rsi14_5m, 2),
            adx14_5m=round(features.adx14_5m, 2),
            plus_di_5m=round(features.plus_di_5m, 2),
            minus_di_5m=round(features.minus_di_5m, 2),
            pivot_point=round(features.pivot_point, 2),
            r1=round(features.r1, 2), r2=round(features.r2, 2), r3=round(features.r3, 2),
            s1=round(features.s1, 2), s2=round(features.s2, 2), s3=round(features.s3, 2),
            pivot_state=features.pivot_state,
            fresh_15m_high=features.fresh_15m_high, fresh_15m_low=features.fresh_15m_low,
            fresh_30m_high=features.fresh_30m_high, fresh_30m_low=features.fresh_30m_low,
            fresh_day_high=features.fresh_day_high, fresh_day_low=features.fresh_day_low,
            trend_alignment_score=round(features.trend_alignment_score, 2),
            clean_trend_score=round(features.clean_trend_score, 2),
            chase_risk_score=round(features.chase_risk_score, 2),
            setup_family=features.setup_family, selection_tier=features.selection_tier,
            previous_state=features.previous_state,
            first_candle_body_ratio=round(first_body_ratio, 3),
            aligned_structure_ratio=round(aligned_structure_ratio, 3),
            opening_range_high=round(opening_range_high, 2),
            opening_range_low=round(opening_range_low, 2),
            opening_range_distance_percent=round(opening_range_distance_percent, 3),
            opening_range_breakout=opening_range_breakout,
            opening_direction_confirmed=opening_direction_confirmed,
            underlying_entry=round(entry, 2), underlying_stop=round(stop, 2),
            underlying_target1=round(t1, 2), underlying_target2=round(t2, 2),
            underlying_target3=round(t3, 2),
            underlying_risk_percent=round(risk_percent, 3),
            trailing_rule=(
                "Trail the underlying behind the latest confirmed 5-minute "
                "swing and EMA20/VWAP structure; no automatic order."
            ),
            reasons=reasons, rejection_reason=rejection,
        )
        self.intraday_engine.update_state(
            symbol=candidate.symbol, stage=candidate.stage,
            direction=candidate.direction,
            movement_score=candidate.movement_capture_score,
            trade_quality_score=candidate.trade_quality_score,
            actionable=candidate.actionable, setup_family=candidate.setup_family,
            when=now,
        )
        return candidate

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

    @staticmethod
    def _movement_capture_score(
        *,
        direction: str,
        move_from_0915_open_percent: float,
        relative_volume: float,
        trend_retention_percent: float,
        range_position: float,
        opening_range_distance_percent: float,
    ) -> float:
        """Measure how much of today's directional move is being captured.

        This score is deliberately separate from trade quality. A stock can
        be a powerful trend leader but still be unsuitable for a fresh entry
        because it is late, extended, or waiting for a controlled pullback.
        """
        directional_move = (
            move_from_0915_open_percent
            if direction == "BULLISH"
            else -move_from_0915_open_percent
        )
        directional_edge = (
            range_position
            if direction == "BULLISH"
            else 1.0 - range_position
        )

        move_score = min(
            max(directional_move, 0.0) / 4.0,
            1.0,
        ) * 35.0
        volume_score = min(
            max(relative_volume - 1.0, 0.0) / 4.0,
            1.0,
        ) * 20.0
        retention_score = (
            min(
                max(trend_retention_percent, 0.0),
                100.0,
            )
            / 100.0
            * 20.0
        )
        edge_score = (
            min(max(directional_edge, 0.0), 1.0)
            * 15.0
        )
        opening_score = min(
            max(opening_range_distance_percent, 0.0) / 1.5,
            1.0,
        ) * 10.0

        return max(
            0.0,
            min(
                100.0,
                move_score
                + volume_score
                + retention_score
                + edge_score
                + opening_score,
            ),
        )

    def _aplus_selective_entry_allowed(self, c: MomentumCandidate) -> bool:
        # Quality-first PAPER gate. Trade count is deliberately not considered.
        # Evidence update from 18-Aug: do NOT kill strong trends. Reject late,
        # overheated entries where the recent move has already stretched too far.
        direction = str(c.direction or "").upper()
        setup = str(c.setup_family or "").upper()
        pivot = str(c.pivot_state or "").upper()

        fresh = (
            c.fresh_15m_high or c.fresh_15m_low
            or c.fresh_30m_high or c.fresh_30m_low
            or c.fresh_day_high or c.fresh_day_low
            or c.opening_range_breakout
        )
        directional_5m = c.recent_move_5m_percent if direction == "BULLISH" else -c.recent_move_5m_percent
        directional_10m = c.recent_move_10m_percent if direction == "BULLISH" else -c.recent_move_10m_percent
        directional_15m = c.recent_move_15m_percent if direction == "BULLISH" else -c.recent_move_15m_percent
        session_move = c.move_from_open_percent if direction == "BULLISH" else -c.move_from_open_percent
        close_move = c.day_change_percent if direction == "BULLISH" else -c.day_change_percent
        vwap_dir = c.vwap_distance_percent if direction == "BULLISH" else -c.vwap_distance_percent
        vwap_aligned = vwap_dir >= 0.0

        if pivot == "PIVOT_TO_R1":
            c.paper_trade_status = "A_PLUS_WAIT_PIVOT_TO_R1"
            return False

        # Late-entry / overheat guard:
        # Targets trades where the immediate move already ran too far before entry.
        # Avoids killing TIINDIA-style strong trends that were not 10m-overheated.
        late_recent = directional_10m > 0.85
        late_vwap = vwap_dir > 0.87
        late_session = session_move > 2.81
        late_close = close_move > 2.96
        if late_recent:
            c.paper_trade_status = "A_PLUS_WAIT_LATE_10M_OVERHEAT"
            return False
        if late_vwap and (directional_5m > 0.25 or directional_15m > 0.45):
            c.paper_trade_status = "A_PLUS_WAIT_LATE_VWAP_EXTENSION"
            return False
        if late_session and (directional_10m > 0.40 or late_vwap):
            c.paper_trade_status = "A_PLUS_WAIT_LATE_SESSION_EXTENSION"
            return False
        if late_close and (directional_10m > 0.40 or late_vwap):
            c.paper_trade_status = "A_PLUS_WAIT_LATE_CLOSE_EXTENSION"
            return False

        if c.chase_risk_score >= 25.0 and abs(c.vwap_distance_percent) >= 0.75:
            c.paper_trade_status = "A_PLUS_WAIT_OVEREXTENDED"
            return False
        if direction == "BULLISH" and c.rsi14_5m >= 85.0 and c.vwap_distance_percent >= 0.60 and directional_10m > 0.85:
            c.paper_trade_status = "A_PLUS_WAIT_BULL_EXHAUSTION"
            return False
        if direction == "BEARISH" and c.rsi14_5m <= 15.0 and c.vwap_distance_percent <= -0.60 and directional_10m > 0.85:
            c.paper_trade_status = "A_PLUS_WAIT_BEAR_EXHAUSTION"
            return False
        if setup == "CLEAN_BEARISH_BREAKDOWN":
            c.paper_trade_status = "A_PLUS_WAIT_BEAR_BREAKDOWN_CONFIRM"
            return False
        if session_move <= 0.0 and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_DIRECTION_CONFLICT"
            return False
        if not vwap_aligned and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_VWAP_ALIGNMENT"
            return False

        current_follow_through = directional_5m > 0.0 or directional_15m > 0.10
        participation = (
            c.relative_volume >= 1.0
            or c.recent_relative_volume_15m >= 1.0
            or c.tape_volume_acceleration_5m >= 1.15
            or c.tape_volume_acceleration_15m >= 1.15
        )
        if not current_follow_through and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_NO_FOLLOW_THROUGH"
            return False
        if not participation:
            c.paper_trade_status = "A_PLUS_WAIT_WEAK_PARTICIPATION"
            return False
        if c.trade_quality_score < 65.0:
            c.paper_trade_status = "A_PLUS_WAIT_QUALITY"
            return False

        # No hard alignment >=60 rejection. TIINDIA had alignment around 54.5
        # but was a clean +33.5% winner.
        if c.trend_alignment_score < 60.0 and c.clean_trend_score < 90.0 and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_ALIGNMENT_STRUCTURE"
            return False
        if c.clean_trend_score < 72.0 and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_CLEAN_STRUCTURE"
            return False
        return True

    def _build_shortlists(
        self,
        candidates: Sequence[MomentumCandidate],
    ) -> tuple[
        list[MomentumCandidate],
        list[MomentumCandidate],
        list[MomentumCandidate],
        list[MomentumCandidate],
    ]:
        """Build non-overlapping all-day operational shortlists."""
        entry_ready: list[MomentumCandidate] = []
        wait_for_pullback: list[MomentumCandidate] = []
        fresh_movement: list[MomentumCandidate] = []
        near_misses: list[MomentumCandidate] = []

        minimum_capture = float(getattr(
            self.settings, "minimum_movement_capture_score", 65.0
        ))
        shortlist_size = max(1, int(getattr(
            self.settings, "movement_shortlist_size", 12
        )))
        minimum_clean = float(getattr(
            self.settings, "minimum_clean_trend_score", 72.0
        ))

        for candidate in candidates:
            candidate.shortlist = ""
            directional_recent15 = (
                candidate.recent_move_15m_percent
                if candidate.direction == "BULLISH"
                else -candidate.recent_move_15m_percent
            )
            directional_edge = (
                candidate.range_position_percent
                if candidate.direction == "BULLISH"
                else 100.0 - candidate.range_position_percent
            )
            aligned_vwap = (
                candidate.vwap_distance_percent > 0
                if candidate.direction == "BULLISH"
                else candidate.vwap_distance_percent < 0
            )

            if candidate.actionable:
                candidate.shortlist = "ENTRY_READY"
                entry_ready.append(candidate)
                continue

            strong_trend = (
                aligned_vwap
                and candidate.completed_5m_bars >= 2
                and candidate.trade_quality_score >= 60.0
                and candidate.trend_alignment_score >= 55.0
                and (
                    candidate.movement_capture_score >= minimum_capture
                    or candidate.clean_trend_score >= minimum_clean
                )
                and (
                    directional_edge >= 62.0
                    or candidate.clean_trend_score >= minimum_clean + 5.0
                )
            )
            if strong_trend or candidate.setup_family == "HEALTHY_PULLBACK":
                candidate.shortlist = "STRONG_TREND_WAIT_FOR_PULLBACK"
                wait_for_pullback.append(candidate)
                continue

            is_fresh = (
                candidate.setup_family in {
                    "FRESH_BREAKOUT", "CONTINUATION_BREAKOUT"
                }
                or abs(directional_recent15) >= float(getattr(
                    self.settings, "minimum_recent_move_15m_percent", 0.45
                ))
            )
            if (
                is_fresh
                and candidate.movement_capture_score >= 50.0
                and candidate.trend_alignment_score >= 45.0
            ):
                candidate.shortlist = "FRESH_MOVEMENT"
                fresh_movement.append(candidate)
                continue

            near = (
                candidate.trade_quality_score >= 58.0
                and (
                    candidate.trend_alignment_score >= 52.0
                    or candidate.clean_trend_score >= 60.0
                    or abs(directional_recent15) >= 0.30
                )
            )
            if near:
                candidate.shortlist = "NEAR_MISSES"
                near_misses.append(candidate)

        entry_ready.sort(
            key=lambda item: (
                item.trade_quality_score,
                item.trend_alignment_score,
                -item.chase_risk_score,
                item.movement_capture_score,
            ),
            reverse=True,
        )
        wait_for_pullback.sort(
            key=lambda item: (
                item.movement_capture_score,
                item.clean_trend_score,
                item.trend_alignment_score,
            ),
            reverse=True,
        )
        fresh_movement.sort(
            key=lambda item: (
                abs(item.recent_move_15m_percent),
                item.trend_alignment_score,
                item.movement_capture_score,
            ),
            reverse=True,
        )
        near_misses.sort(
            key=lambda item: (
                item.trade_quality_score,
                item.trend_alignment_score,
                item.clean_trend_score,
            ),
            reverse=True,
        )

        maximum = self.settings.maximum_report_candidates
        return (
            entry_ready[:maximum],
            wait_for_pullback[:shortlist_size],
            fresh_movement[:maximum],
            near_misses[:maximum],
        )

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
        features: Mapping[str, Any],
    ) -> tuple[str, bool, str]:
        prefix = "BULLISH" if direction == "BULLISH" else "BEARISH"
        current = now.time()

        # Paper signals have no arbitrary intraday clock cutoff.  Before the
        # first completed 5-minute candle there is simply not enough data to
        # validate a momentum entry, so this is a data-readiness gate rather
        # than a time-based trade prohibition.
        if completed_bars < 1:
            return (
                "WAITING_FOR_FIRST_5M_CLOSE",
                False,
                "first completed 5-minute candle is not available",
            )

        if risk_percent > self.settings.maximum_stop_percent:
            return "RISK_TOO_WIDE", False, "structural stop is too wide"

        if not aligned_vwap:
            return "VWAP_CONFLICT", False, "price is on the wrong side of VWAP"

        chase = float(features.get("chase_risk_score") or 0.0)
        maximum_chase = float(getattr(
            self.settings, "maximum_chase_risk_score", 45.0
        ))
        if (
            chase >= maximum_chase
            or extension_atr > self.settings.maximum_extension_atr * 1.35
            or abs(vwap_distance_percent)
            > self.settings.maximum_extension_from_vwap_percent * 1.35
        ):
            return "EXTENDED_NO_ENTRY", False, "trend is strong but entry is overextended"

        recent_rvol = max(
            relative_volume,
            float(features.get("recent_relative_volume_15m") or 0.0),
            float(features.get("tape_volume_acceleration_5m") or 0.0),
            float(features.get("tape_volume_acceleration_15m") or 0.0),
        )
        minimum_rvol = min(
            float(self.settings.minimum_relative_volume),
            float(getattr(self.settings, "minimum_recent_volume_acceleration", 1.30)),
        )
        if recent_rvol < minimum_rvol:
            return "LOW_RELATIVE_VOLUME", False, "session/recent relative volume is insufficient"

        alignment = float(features.get("trend_alignment_score") or 0.0)
        clean = float(features.get("clean_trend_score") or 0.0)
        fresh = bool(features.get("fresh_breakout"))
        pullback = bool(features.get("healthy_pullback"))
        continuation = bool(features.get("continuation_breakout"))
        recent15 = float(features.get("recent_move_15m_percent") or 0.0)
        directional_recent15 = recent15 if direction == "BULLISH" else -recent15
        fresh15_edge = (
            bool(features.get("fresh_15m_high"))
            if direction == "BULLISH"
            else bool(features.get("fresh_15m_low"))
        )

        opening_phase_end = getattr(
            self.settings, "opening_phase_end", self.settings.confirmation_time
        )
        if current <= opening_phase_end:
            if current < self.settings.confirmation_time:
                if not first_alignment or first_body_ratio < 0.40:
                    return "WEAK_OPENING_CANDLE", False, "opening candle quality is weak"
                if completed_bars >= 1 and score >= self.settings.minimum_early_score:
                    return f"EARLY_{prefix}_MOMENTUM", True, ""
                return "EARLY_WATCHLIST", False, "early score below threshold"

            opening_confirmed = (
                opening_range_breakout
                or opening_direction_confirmed
                or fresh
                or clean >= float(getattr(
                    self.settings, "minimum_clean_trend_score", 72.0
                ))
            )
            if score >= self.settings.minimum_confirmed_score and opening_confirmed:
                return f"OPENING_{prefix}_ENTRY_READY", True, ""
            return "MOMENTUM_WATCHLIST", False, "opening movement not confirmed"

        if continuation and score >= float(getattr(
            self.settings, "minimum_continuation_score", 70.0
        )) and alignment >= 60.0:
            return f"CONTINUATION_{prefix}_ENTRY_READY", True, ""

        if fresh and score >= float(getattr(
            self.settings, "minimum_fresh_breakout_score", 72.0
        )) and alignment >= 58.0:
            return f"FRESH_INTRADAY_{prefix}_BREAKOUT", True, ""

        minimum_clean = float(getattr(
            self.settings, "minimum_clean_trend_score", 72.0
        ))
        minimum_recent = float(getattr(
            self.settings, "minimum_recent_move_15m_percent", 0.45
        ))
        if (
            clean >= minimum_clean
            and alignment >= 60.0
            and directional_recent15 >= minimum_recent * 0.65
            and fresh15_edge
        ):
            label = "BREAKOUT" if direction == "BULLISH" else "BREAKDOWN"
            return f"CLEAN_{prefix}_{label}", True, ""

        if pullback:
            return f"HEALTHY_{prefix}_PULLBACK", False, "waiting for continuation confirmation"

        if alignment >= 62.0 or clean >= minimum_clean:
            return (
                f"{prefix}_TREND_WAIT_FOR_PULLBACK",
                False,
                "established trend; wait for a fresh breakout or controlled retest",
            )

        return "MOMENTUM_WATCHLIST", False, "no fresh all-day entry trigger"

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
        account_context: Mapping[str, Any],
        safety_evaluations: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        # PAPER option plan with safe expiry fallback. Safety is never bypassed.
        cached = self._cached_option(candidate.symbol)
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

        option_contract = None
        safety = None
        safety_payload = None
        attempt_errors: list[str] = []

        if cached is not None:
            option_contract = cached
        else:
            expiries: list[str | None] = []
            try:
                if hasattr(self.option_chain, "get_master_expiries"):
                    expiries = list(self.option_chain.get_master_expiries(underlying))
                elif hasattr(self.option_chain, "get_expiries"):
                    expiries = list(self.option_chain.get_expiries(underlying.security_id))
            except Exception as exc:
                logger.warning(
                    "Expiry fallback list failed for %s: %s: %s",
                    candidate.symbol, type(exc).__name__, exc,
                )

            normalized: list[str] = []
            for value in expiries:
                text = str(value or "").strip()[:10]
                if not text:
                    continue
                try:
                    parsed = datetime.fromisoformat(text).date()
                except ValueError:
                    continue
                if parsed >= now.date():
                    normalized.append(parsed.isoformat())

            expiry_attempts: list[str | None] = sorted(set(normalized))[:4]
            if not expiry_attempts:
                expiry_attempts = [None]

            for expiry in expiry_attempts:
                label = expiry or "DEFAULT"
                try:
                    snapshot = (
                        self.option_chain.fetch(underlying, expiry=expiry)
                        if expiry is not None
                        else self.option_chain.fetch(underlying)
                    )
                    selected = self.option_selector.select(
                        snapshot=snapshot,
                        underlying=underlying,
                        recommendation=recommendation,
                        bias=bias,
                    )
                    tentative = self._serializable(selected)
                except OptionSelectionError as exc:
                    attempt_errors.append(f"{label}: {exc}")
                    logger.info(
                        "OPTION_EXPIRY_FALLBACK symbol=%s expiry=%s result=NO_EXECUTABLE_CONTRACT error=%s",
                        candidate.symbol, label, exc,
                    )
                    continue
                except Exception as exc:
                    attempt_errors.append(f"{label}: {type(exc).__name__}: {exc}")
                    logger.warning(
                        "OPTION_EXPIRY_FALLBACK symbol=%s expiry=%s result=FETCH_OR_SELECTION_ERROR error=%s: %s",
                        candidate.symbol, label, type(exc).__name__, exc,
                    )
                    continue

                trial_safety = self.safety_gate.evaluate(
                    symbol=candidate.symbol,
                    option_contract=tentative,
                    now=now,
                    fund_limits=account_context.get("fund_limits") or {},
                    positions=account_context.get("positions") or [],
                    fund_limits_available=bool(account_context.get("fund_limits_fetch_ok")),
                    positions_available=bool(account_context.get("positions_fetch_ok")),
                    candidate_context=candidate.to_dict(),
                )
                trial_payload = trial_safety.to_dict()
                safety_evaluations.append(trial_payload)

                if trial_safety.allowed:
                    option_contract = tentative
                    safety = trial_safety
                    safety_payload = trial_payload
                    self._option_cache[candidate.symbol] = (time.monotonic(), option_contract)
                    logger.info(
                        "OPTION_EXPIRY_FALLBACK symbol=%s expiry=%s result=SELECTED_SAFE",
                        candidate.symbol,
                        str(option_contract.get("expiry") or label),
                    )
                    break

                expiry_only = bool(trial_safety.block_reasons) and all(
                    str(reason).startswith("EXPIRY_SETTLEMENT:")
                    for reason in trial_safety.block_reasons
                )
                if expiry_only:
                    attempt_errors.append(
                        f"{label}: SAFETY_BLOCKED: " + "; ".join(trial_safety.block_reasons)
                    )
                    logger.info(
                        "OPTION_EXPIRY_FALLBACK symbol=%s expiry=%s result=EXPIRY_BLOCK_TRY_NEXT reason=%s",
                        candidate.symbol, label, "; ".join(trial_safety.block_reasons),
                    )
                    continue

                option_contract = tentative
                safety = trial_safety
                safety_payload = trial_payload
                break

            if option_contract is None:
                candidate.option_error = (
                    "EXPIRY_FALLBACK_EXHAUSTED: " + " | ".join(attempt_errors[-4:])
                )
                return None

        if safety is None:
            safety = self.safety_gate.evaluate(
                symbol=candidate.symbol,
                option_contract=option_contract,
                now=now,
                fund_limits=account_context.get("fund_limits") or {},
                positions=account_context.get("positions") or [],
                fund_limits_available=bool(account_context.get("fund_limits_fetch_ok")),
                positions_available=bool(account_context.get("positions_fetch_ok")),
                candidate_context=candidate.to_dict(),
            )
            safety_payload = safety.to_dict()
            safety_evaluations.append(safety_payload)

        candidate.safety_decision = safety.decision
        candidate.safety_block_reasons = list(safety.block_reasons)
        candidate.safety_warnings = list(safety.warnings)

        if not safety.allowed:
            candidate.option_error = "SAFETY_BLOCKED: " + "; ".join(safety.block_reasons)
            return None

        candidate.option_error = ""
        return {
            "generated_at": now.isoformat(),
            "paper_signal_only": True,
            "symbol": candidate.symbol,
            "direction": candidate.direction,
            "stage": candidate.stage,
            "setup_family": candidate.setup_family,
            "selection_tier": candidate.selection_tier,
            "momentum_score": candidate.score,
            "movement_capture_score": candidate.movement_capture_score,
            "trend_alignment_score": candidate.trend_alignment_score,
            "clean_trend_score": candidate.clean_trend_score,
            "chase_risk_score": candidate.chase_risk_score,
            "pivot_state": candidate.pivot_state,
            "recent_move_15m_percent": candidate.recent_move_15m_percent,
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
            "safety_gate": safety_payload,
            "reasons": candidate.reasons,
        }

    def _load_account_safety_context(self) -> dict[str, Any]:
        """Load account safety data with conservative short-lived caching."""
        context: dict[str, Any] = {
            "fund_limits": {},
            "positions": [],
            "fund_limits_fetch_ok": False,
            "positions_fetch_ok": False,
            "errors": [],
            "cache": {"fund_limits": "MISS", "positions": "MISS"},
        }
        now_mono = time.monotonic()

        cached_funds = self._account_cache.get("fund_limits")
        if cached_funds is not None:
            created_at, payload = cached_funds
            age = now_mono - created_at
            if age <= self._fund_cache_seconds:
                context["fund_limits"] = payload
                context["fund_limits_fetch_ok"] = True
                context["cache"]["fund_limits"] = f"HIT age={age:.1f}s"

        if not context["fund_limits_fetch_ok"]:
            try:
                funds = self.client.get_fund_limits()
                context["fund_limits"] = funds
                context["fund_limits_fetch_ok"] = True
                self._account_cache["fund_limits"] = (now_mono, funds)
                context["cache"]["fund_limits"] = "REFRESHED"
            except Exception as exc:
                context["errors"].append(f"fund_limits {type(exc).__name__}: {exc}")
                logger.warning("Safety fund-limit fetch failed: %s", exc)
                if cached_funds is not None:
                    _, payload = cached_funds
                    context["fund_limits"] = payload
                    context["fund_limits_fetch_ok"] = True
                    context["cache"]["fund_limits"] = "STALE_FALLBACK"

        cached_positions = self._account_cache.get("positions")
        if cached_positions is not None:
            created_at, payload = cached_positions
            age = now_mono - created_at
            if age <= self._positions_cache_seconds:
                context["positions"] = payload
                context["positions_fetch_ok"] = True
                context["cache"]["positions"] = f"HIT age={age:.1f}s"

        if not context["positions_fetch_ok"]:
            try:
                positions = self.client.get_positions()
                context["positions"] = positions
                context["positions_fetch_ok"] = True
                self._account_cache["positions"] = (now_mono, positions)
                context["cache"]["positions"] = "REFRESHED"
            except Exception as exc:
                context["errors"].append(f"positions {type(exc).__name__}: {exc}")
                logger.warning("Safety positions fetch failed: %s", exc)
                if cached_positions is not None:
                    _, payload = cached_positions
                    context["positions"] = payload
                    context["positions_fetch_ok"] = True
                    context["cache"]["positions"] = "STALE_FALLBACK"

        return context

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
            trade_quality_score=quote.radar_score,
            movement_capture_score=0.0,
            shortlist="",
            actionable=False,
            ltp=quote.ltp,
            previous_close=quote.previous_close,
            day_open=quote.open,
            open_0915=quote.open,
            day_high=quote.high,
            day_low=quote.low,
            day_change_percent=quote.change_percent,
            gap_percent=quote.gap_percent,
            move_from_open_percent=quote.move_from_open_percent,
            move_from_0915_open_percent=(
                quote.move_from_open_percent
            ),
            open_to_high_percent=quote.open_to_high_percent,
            open_to_low_percent=quote.open_to_low_percent,
            below_day_high_percent=quote.below_day_high_percent,
            above_day_low_percent=quote.above_day_low_percent,
            day_range_percent=quote.day_range_percent,
            range_position=quote.range_position,
            range_position_percent=(
                quote.range_position_percent
            ),
            trend_retention_percent=(
                quote.trend_retention_percent
            ),
            move_type=quote.move_type,
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
            opening_range_distance_percent=0.0,
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

        opening_end = getattr(
            self.settings, "opening_phase_end", self.settings.confirmation_time
        )
        if current <= opening_end:
            return "OPENING_MOMENTUM"
        if current <= getattr(
            self.settings, "morning_continuation_end", clock_time(12, 0)
        ):
            return "MORNING_CONTINUATION"
        if current <= getattr(
            self.settings, "midday_development_end", clock_time(13, 30)
        ):
            return "MIDDAY_DEVELOPMENT"
        if current <= self.settings.session_stop:
            return "AFTERNOON_MOMENTUM"
        return "SESSION_COMPLETE"

    def _new_entries_allowed(self, now: datetime) -> bool:
        """Allow quality-gated PAPER trade generation for the whole session."""
        return (
            self.settings.session_start
            <= now.time()
            <= self.settings.session_stop
        )

    @staticmethod
    def _seconds_until(now: datetime, clock: Any) -> int:
        target = datetime.combine(now.date(), clock, tzinfo=IST)
        return max(0, int((target - now).total_seconds()))

    def _write_reports(self, payload: Mapping[str, Any]) -> None:
        timestamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        intraday_latest = self.report_dir / "intraday_movement_latest.json"
        intraday_archive = self.report_dir / f"intraday_movement_{timestamp}.json"
        # Backward-compatible files used by the existing workflow.
        legacy_latest = self.report_dir / "opening_momentum_latest.json"
        legacy_archive = self.report_dir / f"opening_momentum_{timestamp}.json"

        self._atomic_json(intraday_latest, payload)
        self._atomic_json(intraday_archive, payload)
        self._atomic_json(legacy_latest, payload)
        self._atomic_json(legacy_archive, payload)

        market_watch = payload.get("fno_market_watch", {}) or {}
        self._atomic_json(self.report_dir / "fno_market_watch_latest.json", market_watch)
        self._write_candidate_csv(
            self.report_dir / "fno_market_watch_latest.csv",
            list(market_watch.get("rows", []) or []),
            [
                "symbol", "sector", "open_0915", "ltp", "previous_close",
                "gap_pct", "from_open_pct", "from_prev_close_pct",
                "day_high", "day_low", "range_position_pct", "direction",
            ],
        )

        v2 = payload.get("stock_selection_v2", {}) or {}
        self._atomic_json(
            self.report_dir / "intraday_stock_selection_v2_latest.json",
            v2,
        )
        v2_rows = list(v2.get("top_up", []) or []) + list(v2.get("top_down", []) or [])
        self._write_candidate_csv(
            self.report_dir / "intraday_stock_selection_v2.csv",
            v2_rows,
            [
                "v2_side", "v2_rank", "symbol", "security_id",
                "eligible_option_side", "ltp", "day_open", "previous_close",
                "from_open_pct", "from_prev_close_pct",
            ],
        )

        fields = [
            "symbol", "direction", "stage", "shortlist",
            "score", "trade_quality_score", "movement_capture_score",
            "trend_alignment_score", "clean_trend_score", "chase_risk_score",
            "setup_family", "selection_tier", "previous_state", "actionable",
            "move_type", "previous_close", "day_change_percent", "gap_percent",
            "day_open", "open_0915", "ltp", "move_from_open_percent",
            "move_from_0915_open_percent", "recent_move_5m_percent",
            "recent_move_10m_percent", "recent_move_15m_percent",
            "recent_move_30m_percent", "day_high", "below_day_high_percent",
            "day_low", "above_day_low_percent", "day_range_percent",
            "range_position_percent", "trend_retention_percent",
            "relative_volume", "recent_relative_volume_15m",
            "tape_volume_acceleration_5m", "tape_volume_acceleration_15m",
            "vwap", "vwap_distance_percent", "ema9_5m", "ema20_5m",
            "ema50_5m", "ema9_15m", "ema20_15m", "adx14_5m",
            "plus_di_5m", "minus_di_5m", "rsi14_5m", "atr_5m",
            "extension_atr", "pivot_point", "r1", "r2", "r3",
            "s1", "s2", "s3", "pivot_state", "fresh_15m_high",
            "fresh_15m_low", "fresh_30m_high", "fresh_30m_low",
            "fresh_day_high", "fresh_day_low", "completed_5m_bars",
            "opening_range_high", "opening_range_low",
            "opening_range_distance_percent", "opening_range_breakout",
            "opening_direction_confirmed", "underlying_entry",
            "underlying_stop", "underlying_risk_percent", "rejection_reason",
            "option_error", "safety_decision", "safety_block_reasons",
            "safety_warnings", "paper_trade_id", "paper_trade_status",
        ]

        candidates = list(payload.get("candidates", []) or [])
        shortlists = payload.get("shortlists", {}) or {}
        entry_ready = list(shortlists.get("ENTRY_READY", []) or [])
        fresh = list(shortlists.get("FRESH_MOVEMENT", []) or [])
        wait = list(shortlists.get("STRONG_TREND_WAIT_FOR_PULLBACK", []) or [])
        near = list(shortlists.get("NEAR_MISSES", []) or [])

        outputs = {
            self.report_dir / "intraday_movement_candidates.csv": candidates,
            self.report_dir / "intraday_entry_ready.csv": entry_ready,
            self.report_dir / "intraday_fresh_movement.csv": fresh,
            self.report_dir / "intraday_wait_for_pullback.csv": wait,
            self.report_dir / "intraday_near_misses.csv": near,
            # Backward-compatible CSV names.
            self.report_dir / "opening_momentum_candidates.csv": candidates,
            self.report_dir / "opening_momentum_early_entries.csv": entry_ready,
            self.report_dir / "opening_momentum_wait_for_pullback.csv": wait,
        }
        for path, rows in outputs.items():
            self._write_candidate_csv(path, rows, fields)

    @staticmethod
    def _replace_with_retry(
        temporary: Path,
        path: Path,
        *,
        attempts: int = 7,
        initial_delay: float = 0.05,
    ) -> bool:
        delay=max(0.01,float(initial_delay))
        attempts=max(1,int(attempts))
        for attempt in range(1,attempts+1):
            try:
                os.replace(temporary,path)
                return True
            except (PermissionError,OSError) as exc:
                if attempt>=attempts:
                    logger.warning(
                        "Scanner atomic replace exhausted retries "
                        "(attempts=%s path=%s error=%s: %s)",
                        attempts,path,type(exc).__name__,exc,
                    )
                    return False
                logger.warning(
                    "Scanner atomic replace retry %s/%s "
                    "(path=%s error=%s: %s)",
                    attempt,attempts,path,type(exc).__name__,exc,
                )
                time.sleep(delay)
                delay=min(delay*2.0,0.80)
        return False


    @classmethod
    def _write_candidate_csv(
        cls,
        path: Path,
        rows: Sequence[Mapping[str, Any]],
        fields: Sequence[str],
    ) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=path.parent,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with temporary.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(fields))
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: row.get(key, "") for key in fields})
                handle.flush()
                os.fsync(handle.fileno())
            if not cls._replace_with_retry(temporary, path):
                logger.warning(
                    "Scanner report CSV replace failed after retries; "
                    "previous file preserved and scanner will continue (path=%s)",
                    path,
                )
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _atomic_json(
        cls,
        path: Path,
        payload: Mapping[str, Any],
    ) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=path.parent,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(
                    OpeningMomentumScanner._serializable(payload),
                    handle,
                    indent=2,
                    ensure_ascii=False,
                )
                handle.flush()
                os.fsync(handle.fileno())
            if not cls._replace_with_retry(temporary, path):
                logger.warning(
                    "Scanner report JSON replace failed after retries; "
                    "previous file preserved and scanner will continue (path=%s)",
                    path,
                )
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)

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

# =====================================================================
# APLUS_SCANNER_429_SURVIVAL_V2
# Infrastructure-only wrapper.
# =====================================================================
if not getattr(OpeningMomentumScanner, "_aplus_429_survival_v2_installed", False):
    _aplus_original_run_once_v2 = OpeningMomentumScanner.run_once

    def _aplus_run_once_429_survival_v2(self, *args, **kwargs):
        try:
            return _aplus_original_run_once_v2(self, *args, **kwargs)
        except Exception as exc:
            message = str(exc)
            if "429" not in message and "Too Many Requests" not in message:
                raise

            now_value = kwargs.get("now")
            if now_value is None:
                now_value = datetime.now(IST)

            logger.warning(
                "APLUS_429_CYCLE_SKIPPED time=%s error=%s: %s; scanner remains alive and will retry on next scheduled cycle",
                now_value.isoformat(),
                type(exc).__name__,
                exc,
            )
            time.sleep(10.0)
            return {
                "generated_at": now_value.isoformat(),
                "mode": "PAPER_SIGNAL_ONLY",
                "live_orders_enabled": False,
                "scanner_mode": "CONTINUOUS_INTRADAY_MOVEMENT",
                "cycle_skipped": True,
                "cycle_skip_reason": "DHAN_429_EXHAUSTED",
                "errors": {"dhan_429": f"{type(exc).__name__}: {exc}"},
                "trade_plans": [],
            }

    OpeningMomentumScanner.run_once = _aplus_run_once_429_survival_v2
    OpeningMomentumScanner._aplus_429_survival_v2_installed = True
