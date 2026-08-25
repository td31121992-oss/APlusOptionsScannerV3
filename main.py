from __future__ import annotations

import argparse
import sys
import time

from analytics.pipeline import AnalyticsPipeline
from config import AppConfig
from core.dhan_client import DhanClient
from core.instrument_loader import InstrumentLoader
from core.option_chain import OptionChainService
from core.scanner import Scanner
from core.snapshot_manager import SnapshotManager
from logger import get_logger
from opening_momentum_scanner import OpeningMomentumScanner
from option_selector import OptionSelector
from ranking_engine import RankingEngine
from report_engine import ReportEngine
from strategy_engine import StrategyEngine
from trade_engine import TradeEngine

logger = get_logger(__name__)


def build_scanner(config: AppConfig) -> Scanner:
    """Build the validated full-universe option-chain analytics scanner."""
    client = DhanClient(config.dhan)
    return Scanner(
        loader=InstrumentLoader(config),
        option_chain=OptionChainService(client),
        snapshots=SnapshotManager(),
        pipeline=AnalyticsPipeline(),
        strategy=StrategyEngine(),
        ranking=RankingEngine(),
        trades=TradeEngine(),
        reports=ReportEngine(config.reports.output_dir),
        max_workers=config.scanner.max_workers,
        symbol_retry_count=config.scanner.symbol_retry_count,
        retry_delay_seconds=config.scanner.retry_delay_seconds,
        continue_on_symbol_error=config.scanner.continue_on_symbol_error,
        progress_every=config.scanner.progress_every,
    )


def build_intraday_movement_scanner(config: AppConfig) -> OpeningMomentumScanner:
    """Build the continuous 09:15-15:30 stateful F&O movement scanner."""
    client = DhanClient(config.dhan)
    return OpeningMomentumScanner(
        config=config,
        client=client,
        loader=InstrumentLoader(config),
        option_chain=OptionChainService(client),
        option_selector=OptionSelector(),
    )


# Backward-compatible builder name used by older scripts/tests.
build_opening_momentum_scanner = build_intraday_movement_scanner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="APlus Options Scanner V3")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--once",
        action="store_true",
        help="Run one full-universe option-chain analytics scan and exit.",
    )
    modes.add_argument(
        "--intraday-once",
        action="store_true",
        help="Run one continuous-intraday movement discovery cycle and exit.",
    )
    modes.add_argument(
        "--intraday-movement",
        action="store_true",
        help="Monitor the F&O universe continuously from 09:15 to 15:30.",
    )
    # Legacy aliases retained so the user's existing BAT file/commands keep working.
    modes.add_argument(
        "--opening-once",
        action="store_true",
        help="Legacy alias for --intraday-once.",
    )
    modes.add_argument(
        "--opening-momentum",
        action="store_true",
        help="Legacy alias for --intraday-movement.",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Seconds between recurring full option-chain scans (default: 300).",
    )
    parser.add_argument(
        "--intraday-interval",
        type=int,
        default=None,
        help="Override seconds between intraday radar cycles (minimum 10).",
    )
    parser.add_argument(
        "--opening-interval",
        type=int,
        default=None,
        help="Legacy alias for --intraday-interval.",
    )
    parser.add_argument(
        "--refresh-instruments",
        action="store_true",
        help="Force refresh of the instrument master before the first cycle.",
    )

    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be at least 1 second")
    requested_intraday_interval = (
        args.intraday_interval
        if args.intraday_interval is not None
        else args.opening_interval
    )
    if requested_intraday_interval is not None and requested_intraday_interval < 10:
        parser.error("intraday interval must be at least 10 seconds")
    return args


def main() -> int:
    args = parse_args()
    config = AppConfig.from_env()
    config.ensure_runtime_directories()

    try:
        intraday_once = args.intraday_once or args.opening_once
        intraday_loop = args.intraday_movement or args.opening_momentum
        if intraday_once or intraday_loop:
            scanner = build_intraday_movement_scanner(config)
            settings = config.opening_momentum
            logger.info(
                "Continuous intraday PAPER scanner configured: poll=%ds "
                "trade_window=%s-%s; no intraday clock cutoff",
                settings.poll_seconds,
                settings.session_start,
                settings.session_stop,
            )
            if intraday_once:
                scanner.run_once(
                    force_refresh_instruments=args.refresh_instruments,
                )
                return 0

            interval = (
                args.intraday_interval
                if args.intraday_interval is not None
                else args.opening_interval
            )
            scanner.run_loop(
                force_refresh_instruments=args.refresh_instruments,
                poll_seconds=interval,
            )
            return 0

        scanner = build_scanner(config)
        logger.info(
            "Full scanner configured: max_workers=%d retries=%d progress_every=%d",
            config.scanner.max_workers,
            config.scanner.symbol_retry_count,
            config.scanner.progress_every,
        )
        if args.once:
            scanner.run_once(force_refresh_instruments=args.refresh_instruments)
            return 0

        first_run = True
        while True:
            scanner.run_once(
                force_refresh_instruments=(args.refresh_instruments and first_run),
            )
            first_run = False
            logger.info("Next full scan will start in %d seconds.", args.interval)
            time.sleep(args.interval)

    except KeyboardInterrupt:
        logger.info("Scanner stopped by user.")
        return 130
    except Exception:
        logger.exception("Scanner terminated because of an unhandled error.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
