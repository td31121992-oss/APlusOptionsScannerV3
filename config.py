"""
config.py

Runtime configuration for APlus Options Scanner V3.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time as clock_time
from pathlib import Path

from dotenv import load_dotenv

from dhan_auth import DhanAuthError, resolve_access_token


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    return value


def _float(
    name: str,
    default: float,
    minimum: float | None = None,
) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    return value


def _clock(
    name: str,
    default: str,
) -> clock_time:
    raw = _text(name, default)
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        raise ConfigurationError(
            f"{name} must use HH:MM or HH:MM:SS"
        )
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        return clock_time(hour, minute, second)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must use a valid 24-hour clock time"
        ) from exc


@dataclass(frozen=True, slots=True)
class DhanConfig:
    client_id: str
    access_token: str
    api_base_url: str = "https://api.dhan.co/v2"
    instrument_master_url: str = (
        "https://images.dhan.co/api-data/"
        "api-scrip-master-detailed.csv"
    )
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    option_chain_requests_per_second: float = 0.34
    market_quote_requests_per_second: float = 1.0
    historical_requests_per_second: float = 4.0
    market_quote_batch_size: int = 1000
    user_agent: str = "APlus-Options-Scanner-V3/3.1"
    verify_tls: bool = True

    def __post_init__(self) -> None:
        if not self.client_id:
            raise ConfigurationError("DHAN_CLIENT_ID is missing in .env")
        if not self.access_token:
            raise ConfigurationError("No usable Dhan access token could be resolved")
        if self.market_quote_batch_size < 1:
            raise ConfigurationError(
                "market_quote_batch_size must be at least 1"
            )


@dataclass(frozen=True, slots=True)
class PathConfig:
    project_root: Path
    data_dir: Path
    cache_dir: Path
    snapshot_dir: Path
    report_dir: Path
    log_dir: Path
    instrument_master_file: Path
    instrument_cache_file: Path

    def runtime_directories(self) -> tuple[Path, ...]:
        return (
            self.data_dir,
            self.cache_dir,
            self.snapshot_dir,
            self.report_dir,
            self.log_dir,
        )


@dataclass(frozen=True, slots=True)
class InstrumentConfig:
    refresh_hours: int = 12
    download_on_start: bool = True
    allow_stale_cache_on_download_failure: bool = True
    stale_cache_max_hours: int = 72
    equity_exchange_segment: str = "NSE_EQ"
    equity_instrument_type: str = "EQUITY"
    stock_option_instrument_type: str = "OPTSTK"
    include_symbols: frozenset[str] = field(default_factory=frozenset)
    exclude_symbols: frozenset[str] = field(default_factory=frozenset)
    require_active_contracts: bool = True


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    log_dir: Path = PROJECT_ROOT / "logs"
    log_file: str = "scanner.log"


@dataclass(frozen=True, slots=True)
class ReportConfig:
    output_dir: Path = PROJECT_ROOT / "data" / "reports"


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    max_workers: int = 8
    symbol_retry_count: int = 2
    retry_delay_seconds: float = 1.0
    progress_every: int = 10
    progress_refresh_seconds: int = 5
    show_progress: bool = True
    worker_timeout_seconds: int = 45
    retry_jitter: bool = True
    continue_on_symbol_error: bool = True


@dataclass(frozen=True, slots=True)
class OpeningMomentumConfig:
    """All-day 09:15-15:30 F&O movement-scanner settings.

    The legacy class/field name is retained so existing imports and .env files
    continue to work, but the scanner is no longer opening-session only.
    """

    poll_seconds: int = 60
    session_start: clock_time = clock_time(9, 15)
    earliest_signal_time: clock_time = clock_time(9, 20)
    confirmation_time: clock_time = clock_time(9, 30)
    opening_phase_end: clock_time = clock_time(10, 30)
    morning_continuation_end: clock_time = clock_time(12, 0)
    midday_development_end: clock_time = clock_time(13, 30)
    # Legacy cutoff fields are retained for .env/backward compatibility only.
    # PAPER trade generation is quality-gated for the full 09:15-15:30 session
    # and no longer uses these fields to block a valid setup.
    normal_entry_cutoff: clock_time = clock_time(14, 45)
    latest_entry_time: clock_time = clock_time(15, 5)
    session_stop: clock_time = clock_time(15, 30)
    market_close: clock_time = clock_time(15, 30)

    quote_shortlist_size: int = 50
    candle_shortlist_size: int = 30
    maximum_option_candidates: int = 5
    maximum_report_candidates: int = 30
    historical_workers: int = 4
    history_calendar_days: int = 8
    option_cache_seconds: int = 0
    quote_tape_minutes: int = 65
    paper_trade_rearm_minutes: int = 180

    minimum_stock_price: float = 20.0
    minimum_cumulative_volume: int = 10_000
    minimum_radar_move_percent: float = 0.30
    minimum_relative_volume: float = 1.40
    minimum_recent_move_15m_percent: float = 0.45
    minimum_recent_volume_acceleration: float = 1.30

    minimum_early_score: float = 80.0
    minimum_confirmed_score: float = 75.0
    minimum_fresh_breakout_score: float = 72.0
    minimum_continuation_score: float = 70.0
    minimum_clean_trend_score: float = 72.0
    minimum_movement_capture_score: float = 65.0
    movement_shortlist_size: int = 12
    late_a_plus_minimum_score: float = 90.0
    maximum_chase_risk_score: float = 45.0

    opening_range_breakout_buffer_percent: float = 0.05
    maximum_extension_from_vwap_percent: float = 2.50
    maximum_extension_atr: float = 2.50
    minimum_stop_percent: float = 0.25
    maximum_stop_percent: float = 2.00
    stop_buffer_percent: float = 0.05

    def __post_init__(self) -> None:
        if not (
            self.session_start
            < self.earliest_signal_time
            <= self.confirmation_time
            <= self.opening_phase_end
            <= self.morning_continuation_end
            <= self.midday_development_end
            <= self.normal_entry_cutoff
            < self.latest_entry_time
            <= self.session_stop
            <= self.market_close
        ):
            raise ConfigurationError(
                "Intraday times must be ordered from 09:15 monitoring through "
                "the final entry cutoff and 15:30 session stop"
            )
        if self.quote_shortlist_size < 1:
            raise ConfigurationError("Intraday quote shortlist must be at least 1")
        if not 1 <= self.candle_shortlist_size <= self.quote_shortlist_size:
            raise ConfigurationError(
                "Intraday candle shortlist must be between 1 and quote shortlist"
            )
        if not 1 <= self.maximum_option_candidates <= self.candle_shortlist_size:
            raise ConfigurationError(
                "Maximum option candidates must be between 1 and candle shortlist"
            )
        for name, value in (
            ("minimum_early_score", self.minimum_early_score),
            ("minimum_confirmed_score", self.minimum_confirmed_score),
            ("minimum_fresh_breakout_score", self.minimum_fresh_breakout_score),
            ("minimum_continuation_score", self.minimum_continuation_score),
            ("minimum_clean_trend_score", self.minimum_clean_trend_score),
            ("minimum_movement_capture_score", self.minimum_movement_capture_score),
            ("late_a_plus_minimum_score", self.late_a_plus_minimum_score),
            ("maximum_chase_risk_score", self.maximum_chase_risk_score),
        ):
            if not 0 <= value <= 100:
                raise ConfigurationError(f"{name} must be between 0 and 100")
        if self.maximum_stop_percent <= self.minimum_stop_percent:
            raise ConfigurationError(
                "Intraday maximum stop percent must exceed minimum stop percent"
            )
        if self.quote_tape_minutes < 35:
            raise ConfigurationError("Quote tape must retain at least 35 minutes")
        if self.paper_trade_rearm_minutes < 5:
            raise ConfigurationError(
                "Paper-trade rearm minutes must be at least 5"
            )


@dataclass(frozen=True, slots=True)
class AppConfig:
    dhan: DhanConfig
    paths: PathConfig
    instruments: InstrumentConfig
    logging: LoggingConfig
    reports: ReportConfig
    scanner: ScannerConfig
    opening_momentum: OpeningMomentumConfig = field(
        default_factory=OpeningMomentumConfig
    )

    @classmethod
    def from_env(cls) -> "AppConfig":
        data_dir = PROJECT_ROOT / "data"
        cache_dir = data_dir / "cache"
        snapshot_dir = data_dir / "snapshots"
        report_dir = data_dir / "reports"
        log_dir = PROJECT_ROOT / "logs"

        include_symbols = frozenset(
            item.strip().upper()
            for item in _text("APLUS_INCLUDE_SYMBOLS").split(",")
            if item.strip()
        )
        exclude_symbols = frozenset(
            item.strip().upper()
            for item in _text("APLUS_EXCLUDE_SYMBOLS").split(",")
            if item.strip()
        )

        dhan_client_id = _text("DHAN_CLIENT_ID")
        try:
            dhan_access_token = resolve_access_token(
                project_root=PROJECT_ROOT,
                client_id=dhan_client_id,
                env_token=_text("DHAN_ACCESS_TOKEN"),
            )
        except DhanAuthError as exc:
            raise ConfigurationError(str(exc)) from exc

        return cls(
            dhan=DhanConfig(
                client_id=dhan_client_id,
                access_token=dhan_access_token,
                api_base_url=_text(
                    "DHAN_API_BASE_URL",
                    "https://api.dhan.co/v2",
                ),
                instrument_master_url=_text(
                    "DHAN_INSTRUMENT_MASTER_URL",
                    "https://images.dhan.co/api-data/"
                    "api-scrip-master-detailed.csv",
                ),
                connect_timeout_seconds=_float(
                    "API_CONNECT_TIMEOUT",
                    5.0,
                    0.1,
                ),
                read_timeout_seconds=_float(
                    "API_READ_TIMEOUT",
                    30.0,
                    0.1,
                ),
                max_retries=_int("API_RETRIES", 2, 0),
                retry_backoff_seconds=_float(
                    "API_RETRY_DELAY",
                    1.0,
                    0.0,
                ),
                option_chain_requests_per_second=_float(
                    "OPTION_CHAIN_REQUESTS_PER_SECOND",
                    0.34,
                    0.01,
                ),
                market_quote_requests_per_second=_float(
                    "MARKET_QUOTE_REQUESTS_PER_SECOND",
                    1.0,
                    0.01,
                ),
                historical_requests_per_second=_float(
                    "HISTORICAL_REQUESTS_PER_SECOND",
                    4.0,
                    0.01,
                ),
                market_quote_batch_size=_int(
                    "MARKET_QUOTE_BATCH_SIZE",
                    1000,
                    1,
                ),
                verify_tls=_bool("VERIFY_TLS", True),
            ),
            paths=PathConfig(
                project_root=PROJECT_ROOT,
                data_dir=data_dir,
                cache_dir=cache_dir,
                snapshot_dir=snapshot_dir,
                report_dir=report_dir,
                log_dir=log_dir,
                instrument_master_file=(
                    cache_dir / "api-scrip-master-detailed.csv"
                ),
                instrument_cache_file=(
                    cache_dir / "instrument_universe.json"
                ),
            ),
            instruments=InstrumentConfig(
                refresh_hours=_int(
                    "APLUS_INSTRUMENT_REFRESH_HOURS",
                    12,
                    1,
                ),
                download_on_start=_bool(
                    "APLUS_DOWNLOAD_INSTRUMENTS_ON_START",
                    True,
                ),
                allow_stale_cache_on_download_failure=_bool(
                    "APLUS_ALLOW_STALE_INSTRUMENT_CACHE",
                    True,
                ),
                stale_cache_max_hours=_int(
                    "APLUS_STALE_CACHE_MAX_HOURS",
                    72,
                    1,
                ),
                include_symbols=include_symbols,
                exclude_symbols=exclude_symbols,
            ),
            logging=LoggingConfig(
                level=_text("LOG_LEVEL", "INFO").upper(),
                log_dir=log_dir,
                log_file=_text("LOG_FILE", "scanner.log"),
            ),
            reports=ReportConfig(output_dir=report_dir),
            scanner=ScannerConfig(
                max_workers=_int("SCANNER_MAX_WORKERS", 8, 1),
                symbol_retry_count=_int("SCANNER_RETRIES", 2, 0),
                retry_delay_seconds=_float(
                    "SCANNER_RETRY_DELAY",
                    1.0,
                    0.0,
                ),
                progress_every=_int(
                    "SCANNER_PROGRESS_EVERY",
                    10,
                    1,
                ),
                progress_refresh_seconds=_int(
                    "SCANNER_PROGRESS_REFRESH",
                    5,
                    1,
                ),
                show_progress=_bool(
                    "SCANNER_SHOW_PROGRESS",
                    True,
                ),
                worker_timeout_seconds=_int(
                    "SCANNER_WORKER_TIMEOUT",
                    45,
                    5,
                ),
                retry_jitter=_bool(
                    "SCANNER_RETRY_JITTER",
                    True,
                ),
                continue_on_symbol_error=_bool(
                    "SCANNER_CONTINUE_ON_ERROR",
                    True,
                ),
            ),
            opening_momentum=OpeningMomentumConfig(
                poll_seconds=_int(
                    "INTRADAY_POLL_SECONDS",
                    _int("OPENING_POLL_SECONDS", 60, 10),
                    10,
                ),
                session_start=_clock("INTRADAY_SESSION_START", "09:15"),
                earliest_signal_time=_clock("INTRADAY_EARLIEST_SIGNAL", "09:20"),
                confirmation_time=_clock("INTRADAY_CONFIRMATION_TIME", "09:30"),
                opening_phase_end=_clock("INTRADAY_OPENING_PHASE_END", "10:30"),
                morning_continuation_end=_clock("INTRADAY_MORNING_END", "12:00"),
                midday_development_end=_clock("INTRADAY_MIDDAY_END", "13:30"),
                normal_entry_cutoff=_clock("INTRADAY_NORMAL_ENTRY_CUTOFF", "14:45"),
                latest_entry_time=_clock("INTRADAY_LATEST_ENTRY", "15:05"),
                session_stop=_clock("INTRADAY_SESSION_STOP", "15:30"),
                market_close=_clock("MARKET_CLOSE_TIME", "15:30"),
                quote_shortlist_size=_int(
                    "INTRADAY_QUOTE_SHORTLIST",
                    _int("OPENING_QUOTE_SHORTLIST", 50, 1),
                    1,
                ),
                candle_shortlist_size=_int(
                    "INTRADAY_CANDLE_SHORTLIST",
                    _int("OPENING_CANDLE_SHORTLIST", 30, 1),
                    1,
                ),
                maximum_option_candidates=_int(
                    "INTRADAY_MAX_OPTION_CANDIDATES",
                    _int("OPENING_MAX_OPTION_CANDIDATES", 5, 1),
                    1,
                ),
                maximum_report_candidates=_int(
                    "INTRADAY_MAX_REPORT_CANDIDATES", 30, 1
                ),
                historical_workers=_int(
                    "INTRADAY_HISTORICAL_WORKERS",
                    _int("OPENING_HISTORICAL_WORKERS", 4, 1),
                    1,
                ),
                history_calendar_days=_int("INTRADAY_HISTORY_DAYS", 8, 2),
                option_cache_seconds=_int("INTRADAY_OPTION_CACHE_SECONDS", 0, 0),
                quote_tape_minutes=_int("INTRADAY_QUOTE_TAPE_MINUTES", 65, 35),
                paper_trade_rearm_minutes=_int("INTRADAY_PAPER_TRADE_REARM_MINUTES", 180, 5),
                minimum_stock_price=_float("INTRADAY_MIN_STOCK_PRICE", 20.0, 0.01),
                minimum_cumulative_volume=_int("INTRADAY_MIN_CUMULATIVE_VOLUME", 10_000, 0),
                minimum_radar_move_percent=_float("INTRADAY_MIN_RADAR_MOVE_PERCENT", 0.30, 0.0),
                minimum_relative_volume=_float("INTRADAY_MIN_RELATIVE_VOLUME", 1.40, 0.0),
                minimum_recent_move_15m_percent=_float("INTRADAY_MIN_RECENT_MOVE_15M", 0.45, 0.0),
                minimum_recent_volume_acceleration=_float("INTRADAY_MIN_VOLUME_ACCELERATION", 1.30, 0.0),
                minimum_early_score=_float("INTRADAY_MIN_EARLY_SCORE", 80.0, 0.0),
                minimum_confirmed_score=_float("INTRADAY_MIN_CONFIRMED_SCORE", 75.0, 0.0),
                minimum_fresh_breakout_score=_float("INTRADAY_MIN_FRESH_BREAKOUT_SCORE", 72.0, 0.0),
                minimum_continuation_score=_float("INTRADAY_MIN_CONTINUATION_SCORE", 70.0, 0.0),
                minimum_clean_trend_score=_float("INTRADAY_MIN_CLEAN_TREND_SCORE", 72.0, 0.0),
                minimum_movement_capture_score=_float("INTRADAY_MIN_MOVEMENT_CAPTURE_SCORE", 65.0, 0.0),
                movement_shortlist_size=_int("INTRADAY_MOVEMENT_SHORTLIST_SIZE", 12, 1),
                late_a_plus_minimum_score=_float("INTRADAY_LATE_A_PLUS_SCORE", 90.0, 0.0),
                maximum_chase_risk_score=_float("INTRADAY_MAX_CHASE_RISK_SCORE", 45.0, 0.0),
                opening_range_breakout_buffer_percent=_float("INTRADAY_BREAKOUT_BUFFER_PERCENT", 0.05, 0.0),
                maximum_extension_from_vwap_percent=_float("INTRADAY_MAX_VWAP_EXTENSION_PERCENT", 2.50, 0.0),
                maximum_extension_atr=_float("INTRADAY_MAX_EXTENSION_ATR", 2.50, 0.0),
                minimum_stop_percent=_float("INTRADAY_MIN_STOP_PERCENT", 0.25, 0.01),
                maximum_stop_percent=_float("INTRADAY_MAX_STOP_PERCENT", 2.00, 0.02),
                stop_buffer_percent=_float("INTRADAY_STOP_BUFFER_PERCENT", 0.05, 0.0),
            ),
        )

    def ensure_runtime_directories(self) -> None:
        for directory in self.paths.runtime_directories():
            directory.mkdir(parents=True, exist_ok=True)


CONFIG = AppConfig.from_env()


__all__ = [
    "AppConfig",
    "CONFIG",
    "ConfigurationError",
    "DhanConfig",
    "InstrumentConfig",
    "LoggingConfig",
    "OpeningMomentumConfig",
    "PathConfig",
    "ReportConfig",
    "ScannerConfig",
]
