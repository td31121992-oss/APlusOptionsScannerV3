"""
core/instrument_loader.py

Load Dhan's detailed instrument master and build the NSE stock-option universe.
Contract metadata includes the exact derivative security ID, lot size and tick
size required by executable option-contract selection.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests

from config import AppConfig
from logger import get_logger


logger = get_logger(__name__)

_EQUITY_SERIES_INSTRUMENT_TYPE = "ES"

REQUIRED_COLUMNS = (
    "EXCH_ID",
    "SEGMENT",
    "SECURITY_ID",
    "INSTRUMENT",
    "INSTRUMENT_TYPE",
    "UNDERLYING_SECURITY_ID",
    "UNDERLYING_SYMBOL",
    "SYMBOL_NAME",
    "DISPLAY_NAME",
    "LOT_SIZE",
    "SM_EXPIRY_DATE",
    "STRIKE_PRICE",
    "OPTION_TYPE",
    "TICK_SIZE",
)


class InstrumentLoaderError(RuntimeError):
    """Raised when the instrument master cannot build a safe universe."""


@dataclass(slots=True)
class DerivativeContract:
    derivative_security_id: str
    trading_symbol: str
    display_name: str
    expiry: str
    strike: float
    option_type: str
    lot_size: int
    tick_size: float
    exchange_segment: str = "NSE_FNO"


@dataclass(slots=True)
class UnderlyingInstrument:
    symbol: str
    security_id: str
    exchange_segment: str
    contracts: list[DerivativeContract] = field(default_factory=list)

    @property
    def contract_count(self) -> int:
        return len(self.contracts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InstrumentLoader:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._universe: dict[str, UnderlyingInstrument] = {}

    def load(self, *, force_refresh: bool = False) -> "InstrumentLoader":
        logger.info("Loading instrument master")
        self._ensure_instrument_master(force_refresh=force_refresh)

        frame = pd.read_csv(
            self.config.paths.instrument_master_file,
            low_memory=False,
        )
        logger.info("Instrument master rows loaded: %d", len(frame))

        self._validate(frame)
        self._universe = self._build_universe(frame)
        self._save_cache()

        logger.info(
            "Instrument universe built: %d symbols",
            len(self._universe),
        )
        return self

    def get_universe(self) -> list[UnderlyingInstrument]:
        return sorted(
            self._universe.values(),
            key=lambda item: item.symbol,
        )

    def get(self, symbol: str) -> UnderlyingInstrument | None:
        return self._universe.get(str(symbol).strip().upper())

    def _master_age_hours(self) -> float | None:
        path = self.config.paths.instrument_master_file
        if not path.exists():
            return None
        return (time.time() - path.stat().st_mtime) / 3600.0

    def _download_instrument_master(self) -> bool:
        url = self.config.dhan.instrument_master_url
        logger.info("Downloading instrument master from %s ...", url)

        try:
            response = requests.get(
                url,
                timeout=(
                    self.config.dhan.connect_timeout_seconds,
                    self.config.dhan.read_timeout_seconds,
                ),
                verify=self.config.dhan.verify_tls,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "Instrument master download failed (%s): %s",
                type(exc).__name__,
                exc,
            )
            return False

        path = self.config.paths.instrument_master_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        logger.info(
            "Instrument master downloaded: %s (%d bytes)",
            path,
            len(response.content),
        )
        return True

    def _ensure_instrument_master(
        self,
        *,
        force_refresh: bool = False,
    ) -> None:
        cfg = self.config.instruments
        age_hours = self._master_age_hours()
        is_stale = (
            age_hours is None
            or age_hours > cfg.refresh_hours
        )
        should_download = (
            force_refresh
            or cfg.download_on_start
            or is_stale
        )

        downloaded = (
            self._download_instrument_master()
            if should_download
            else True
        )
        if downloaded:
            return

        age_hours = self._master_age_hours()
        if age_hours is None:
            raise InstrumentLoaderError(
                f"{self.config.paths.instrument_master_file} not found "
                "and download failed."
            )
        if not cfg.allow_stale_cache_on_download_failure:
            raise InstrumentLoaderError(
                "Instrument master download failed and stale-cache "
                "fallback is disabled."
            )
        if age_hours > cfg.stale_cache_max_hours:
            raise InstrumentLoaderError(
                "Instrument master download failed and cached file is "
                f"{age_hours:.1f}h old, exceeding "
                f"stale_cache_max_hours={cfg.stale_cache_max_hours}."
            )

        logger.warning(
            "Using stale instrument master cache (%.1fh old).",
            age_hours,
        )

    @staticmethod
    def _validate(frame: pd.DataFrame) -> None:
        missing = [
            column
            for column in REQUIRED_COLUMNS
            if column not in frame.columns
        ]
        if missing:
            raise InstrumentLoaderError(
                "Instrument master is missing columns required for "
                f"executable options: {missing}. Use Dhan's detailed "
                "instrument master CSV."
            )

    def _build_universe(
        self,
        frame: pd.DataFrame,
    ) -> dict[str, UnderlyingInstrument]:
        cfg = self.config.instruments

        equity_rows = frame[
            (frame["EXCH_ID"] == "NSE")
            & (frame["SEGMENT"] == "E")
            & (
                frame["INSTRUMENT"]
                == cfg.equity_instrument_type
            )
            & (
                frame["INSTRUMENT_TYPE"]
                == _EQUITY_SERIES_INSTRUMENT_TYPE
            )
        ]

        derivative_rows = frame[
            (frame["EXCH_ID"] == "NSE")
            & (frame["SEGMENT"] == "D")
            & (
                frame["INSTRUMENT"]
                == cfg.stock_option_instrument_type
            )
        ]

        logger.info(
            "NSE equity rows: %d | NSE stock-option rows: %d",
            len(equity_rows),
            len(derivative_rows),
        )

        by_underlying_id: dict[int, UnderlyingInstrument] = {}
        for _, row in equity_rows.iterrows():
            security_id = self._safe_int(row.get("SECURITY_ID"))
            symbol = self._clean_text(row.get("SYMBOL_NAME")).upper()

            if security_id is None or not symbol:
                continue

            by_underlying_id[security_id] = UnderlyingInstrument(
                symbol=symbol,
                security_id=str(security_id),
                exchange_segment=cfg.equity_exchange_segment,
            )

        unmatched = 0
        invalid_contracts = 0

        for _, row in derivative_rows.iterrows():
            underlying_id = self._safe_int(
                row.get("UNDERLYING_SECURITY_ID")
            )
            derivative_id = self._safe_int(row.get("SECURITY_ID"))

            if (
                underlying_id is None
                or derivative_id is None
                or underlying_id not in by_underlying_id
            ):
                unmatched += 1
                continue

            expiry = self._normalize_expiry(
                row.get("SM_EXPIRY_DATE")
            )
            strike = self._safe_float(row.get("STRIKE_PRICE"))
            option_type = self._normalize_option_type(
                row.get("OPTION_TYPE")
            )
            lot_size = self._safe_int(row.get("LOT_SIZE"))
            tick_size = self._safe_float(row.get("TICK_SIZE"))

            if (
                not expiry
                or strike is None
                or strike <= 0
                or not option_type
                or lot_size is None
                or lot_size <= 0
                or tick_size is None
                or tick_size <= 0
            ):
                invalid_contracts += 1
                continue

            underlying = by_underlying_id[underlying_id]
            clean_symbol = self._clean_text(
                row.get("UNDERLYING_SYMBOL")
            ).upper()
            if clean_symbol:
                underlying.symbol = clean_symbol

            underlying.contracts.append(
                DerivativeContract(
                    derivative_security_id=str(derivative_id),
                    trading_symbol=self._clean_text(
                        row.get("SYMBOL_NAME")
                    ),
                    display_name=self._clean_text(
                        row.get("DISPLAY_NAME")
                    ),
                    expiry=expiry,
                    strike=float(strike),
                    option_type=option_type,
                    lot_size=int(lot_size),
                    tick_size=float(tick_size),
                )
            )

        logger.info("Unmatched derivative contracts: %d", unmatched)
        logger.info("Invalid derivative contracts skipped: %d", invalid_contracts)

        universe: dict[str, UnderlyingInstrument] = {}
        for underlying in by_underlying_id.values():
            underlying.contracts.sort(
                key=lambda contract: (
                    contract.expiry,
                    contract.strike,
                    contract.option_type,
                )
            )

            if cfg.require_active_contracts and not underlying.contracts:
                continue
            if (
                cfg.include_symbols
                and underlying.symbol not in cfg.include_symbols
            ):
                continue
            if underlying.symbol in cfg.exclude_symbols:
                continue

            universe[underlying.symbol] = underlying

        return universe

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            if value is None or pd.isna(value):
                return None
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            if value is None or pd.isna(value):
                return None
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None

        if result != result or result in (float("inf"), float("-inf")):
            return None
        return result

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass

        text = str(value).strip()
        return "" if text.upper() in {"NAN", "NAT", "NONE"} else text

    @classmethod
    def _normalize_expiry(cls, value: Any) -> str:
        text = cls._clean_text(value)
        if not text:
            return ""

        if isinstance(value, (date, datetime)):
            return (
                value.date().isoformat()
                if isinstance(value, datetime)
                else value.isoformat()
            )

        for candidate in (text, text[:10]):
            for fmt in (
                "%Y-%m-%d",
                "%d-%m-%Y",
                "%d/%m/%Y",
                "%Y/%m/%d",
            ):
                try:
                    return datetime.strptime(
                        candidate,
                        fmt,
                    ).date().isoformat()
                except ValueError:
                    continue
        return ""

    @classmethod
    def _normalize_option_type(cls, value: Any) -> str:
        text = cls._clean_text(value).upper()
        if text in {"CE", "CALL", "C"}:
            return "CE"
        if text in {"PE", "PUT", "P"}:
            return "PE"
        return ""

    def _save_cache(self) -> None:
        path = self.config.paths.instrument_cache_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            symbol: instrument.to_dict()
            for symbol, instrument in self._universe.items()
        }
        path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Instrument cache saved: %s", path)


__all__ = [
    "DerivativeContract",
    "InstrumentLoader",
    "InstrumentLoaderError",
    "UnderlyingInstrument",
]
