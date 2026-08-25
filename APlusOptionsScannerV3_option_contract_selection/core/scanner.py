"""
core/scanner.py

End-to-end scanner orchestration with executable option-contract selection.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from analytics.models import (
    OptionChainSnapshot,
    RankedStock,
    StrategySignal,
    TradeRecommendation,
)
from analytics.pipeline import AnalyticsPipeline, AnalyticsResult
from logger import get_logger
from ranking_engine import RankingEngine
from report_engine import ReportEngine
from strategy_engine import StrategyEngine
from trade_engine import TradeEngine

from .instrument_loader import InstrumentLoader, UnderlyingInstrument
from .option_chain import OptionChainService
from .snapshot_manager import SnapshotManager


logger = get_logger(__name__)


class ScannerError(RuntimeError):
    """Raised when a scanner run cannot be completed."""


@dataclass(slots=True)
class SymbolScanResult:
    symbol: str
    underlying_ltp: float
    signal: StrategySignal
    analytics: AnalyticsResult
    snapshot: OptionChainSnapshot
    underlying: UnderlyingInstrument
    snapshot_path: str | None = None


@dataclass(slots=True)
class ScanRunResult:
    scan_id: str
    started_at: str
    completed_at: str
    universe: int
    succeeded: int
    failed: int
    ranked: int
    recommendations: int
    rankings: list[RankedStock] = field(default_factory=list)
    trades: list[TradeRecommendation] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Scanner:
    def __init__(
        self,
        *,
        loader: InstrumentLoader,
        option_chain: OptionChainService,
        snapshots: SnapshotManager,
        pipeline: AnalyticsPipeline,
        strategy: StrategyEngine,
        ranking: RankingEngine,
        trades: TradeEngine,
        reports: ReportEngine,
        max_workers: int = 1,
        symbol_retry_count: int = 1,
        retry_delay_seconds: float = 1.0,
        continue_on_symbol_error: bool = True,
        progress_every: int = 10,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if symbol_retry_count < 0:
            raise ValueError("symbol_retry_count cannot be negative")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")
        if progress_every < 1:
            raise ValueError("progress_every must be at least 1")

        self.loader = loader
        self.option_chain = option_chain
        self.snapshots = snapshots
        self.pipeline = pipeline
        self.strategy = strategy
        self.ranking = ranking
        self.trades = trades
        self.reports = reports
        self.max_workers = max_workers
        self.symbol_retry_count = symbol_retry_count
        self.retry_delay_seconds = retry_delay_seconds
        self.continue_on_symbol_error = continue_on_symbol_error
        self.progress_every = progress_every

    def run_once(
        self,
        *,
        force_refresh_instruments: bool = False,
    ) -> ScanRunResult:
        scan_id = uuid.uuid4().hex[:12]
        started = datetime.now(timezone.utc)
        logger.info("Starting scanner run scan_id=%s", scan_id)

        universe = self.loader.load(
            force_refresh=force_refresh_instruments
        ).get_universe()
        if not universe:
            raise ScannerError("Instrument universe is empty")

        logger.info(
            "Instrument universe ready scan_id=%s symbols=%d",
            scan_id,
            len(universe),
        )

        successful: list[SymbolScanResult] = []
        errors: dict[str, str] = {}

        if self.max_workers == 1:
            self._run_sequential(
                universe=universe,
                successful=successful,
                errors=errors,
                scan_id=scan_id,
            )
        else:
            self._run_parallel(
                universe=universe,
                successful=successful,
                errors=errors,
                scan_id=scan_id,
            )

        signals = [item.signal for item in successful]
        prices = {
            item.symbol: item.underlying_ltp
            for item in successful
            if item.underlying_ltp > 0
        }
        current_snapshots = {
            item.symbol: item.snapshot
            for item in successful
        }
        underlying_instruments = {
            item.symbol: item.underlying
            for item in successful
        }

        rankings = self.ranking.rank(signals)
        recommendations = self.trades.generate(
            rankings,
            prices,
            snapshots=current_snapshots,
            underlyings=underlying_instruments,
        )
        self.reports.generate(rankings, recommendations)

        completed = datetime.now(timezone.utc)
        result = ScanRunResult(
            scan_id=scan_id,
            started_at=self._iso(started),
            completed_at=self._iso(completed),
            universe=len(universe),
            succeeded=len(successful),
            failed=len(errors),
            ranked=len(rankings),
            recommendations=len(recommendations),
            rankings=rankings,
            trades=recommendations,
            errors=errors,
        )

        logger.info(
            "Scanner run completed scan_id=%s universe=%d "
            "succeeded=%d failed=%d ranked=%d recommendations=%d",
            result.scan_id,
            result.universe,
            result.succeeded,
            result.failed,
            result.ranked,
            result.recommendations,
        )
        return result

    def _run_sequential(
        self,
        *,
        universe: list[UnderlyingInstrument],
        successful: list[SymbolScanResult],
        errors: dict[str, str],
        scan_id: str,
    ) -> None:
        for index, underlying in enumerate(universe, start=1):
            try:
                successful.append(self._scan_with_retry(underlying))
            except Exception as exc:
                errors[underlying.symbol] = str(exc)
                logger.exception(
                    "Scan failed for %s scan_id=%s",
                    underlying.symbol,
                    scan_id,
                )
                if not self.continue_on_symbol_error:
                    raise ScannerError(
                        f"Scan stopped after failure for {underlying.symbol}"
                    ) from exc

            if index % self.progress_every == 0 or index == len(universe):
                logger.info(
                    "Scanned %d/%d symbols scan_id=%s",
                    index,
                    len(universe),
                    scan_id,
                )

    def _run_parallel(
        self,
        *,
        universe: list[UnderlyingInstrument],
        successful: list[SymbolScanResult],
        errors: dict[str, str],
        scan_id: str,
    ) -> None:
        completed_count = 0
        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="aplus-scan",
        ) as executor:
            futures = {
                executor.submit(
                    self._scan_with_retry,
                    underlying,
                ): underlying
                for underlying in universe
            }

            for future in as_completed(futures):
                underlying = futures[future]
                completed_count += 1
                try:
                    successful.append(future.result())
                except Exception as exc:
                    errors[underlying.symbol] = str(exc)
                    logger.exception(
                        "Scan failed for %s scan_id=%s",
                        underlying.symbol,
                        scan_id,
                    )
                    if not self.continue_on_symbol_error:
                        for pending in futures:
                            pending.cancel()
                        raise ScannerError(
                            f"Scan stopped after failure for {underlying.symbol}"
                        ) from exc

                if (
                    completed_count % self.progress_every == 0
                    or completed_count == len(universe)
                ):
                    logger.info(
                        "Scanned %d/%d symbols scan_id=%s",
                        completed_count,
                        len(universe),
                        scan_id,
                    )

    def _scan_with_retry(
        self,
        underlying: UnderlyingInstrument,
    ) -> SymbolScanResult:
        last_error: Exception | None = None
        attempts = self.symbol_retry_count + 1

        for attempt in range(1, attempts + 1):
            try:
                return self._scan_symbol(underlying)
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "Retrying %s after attempt %d/%d failed: %s",
                    underlying.symbol,
                    attempt,
                    attempts,
                    exc,
                )
                time.sleep(self.retry_delay_seconds * attempt)

        assert last_error is not None
        raise last_error

    def _scan_symbol(
        self,
        underlying: UnderlyingInstrument,
    ) -> SymbolScanResult:
        current = self.option_chain.fetch(underlying)
        previous = self.snapshots.load_previous(current)
        current = self.snapshots.apply_changes(current, previous)

        previous_ltp = (
            previous.underlying_ltp
            if previous is not None
            else None
        )
        analytics = self.pipeline.analyze(
            current,
            previous_snapshot_available=previous is not None,
            previous_underlying_ltp=previous_ltp,
        )
        signal = self.strategy.analyze(
            current.symbol,
            analytics.confidence,
        )
        snapshot_path = self.snapshots.save(current)

        logger.debug(
            "Symbol processed symbol=%s expiry=%s confidence=%.2f "
            "bias=%s previous_snapshot=%s",
            current.symbol,
            current.expiry,
            signal.confidence,
            signal.bias.value,
            previous is not None,
        )

        return SymbolScanResult(
            symbol=current.symbol,
            underlying_ltp=current.underlying_ltp,
            signal=signal,
            analytics=analytics,
            snapshot=current,
            underlying=underlying,
            snapshot_path=(
                str(snapshot_path) if snapshot_path else None
            ),
        )

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace(
            "+00:00",
            "Z",
        )


__all__ = [
    "ScanRunResult",
    "Scanner",
    "ScannerError",
    "SymbolScanResult",
]
