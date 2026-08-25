"""
core/option_chain.py

Dhan option-chain retrieval and normalization for APlus Options Scanner V3.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from analytics.enums import OptionSide
from analytics.models import OptionChainSnapshot, OptionLeg, StrikeData
from logger import get_logger


logger = get_logger(__name__)


class OptionChainError(RuntimeError):
    """Raised when expiry or option-chain data cannot be obtained or normalized."""


class DhanOptionChainClient(Protocol):
    """Minimum Dhan client interface required by this service."""

    def get_expiries(
        self,
        security_id: int,
        segment: str = "NSE_EQ",
    ) -> Any:
        ...

    def get_option_chain(
        self,
        security_id: int,
        expiry: str,
        segment: str = "NSE_EQ",
    ) -> Mapping[str, Any]:
        ...


class UnderlyingLike(Protocol):
    """Minimum underlying-instrument interface required by this service."""

    symbol: str
    security_id: Any
    contracts: Sequence[Any]


class OptionChainService:
    """Fetch and normalize Dhan option chains using instrument-master expiries."""

    def __init__(
        self,
        client: DhanOptionChainClient,
        *,
        underlying_segment: str = "NSE_EQ",
        expiry_index: int = 0,
    ) -> None:
        if expiry_index < 0:
            raise ValueError("expiry_index cannot be negative")

        self.client = client
        self.underlying_segment = underlying_segment
        self.expiry_index = expiry_index

    def fetch(
        self,
        underlying: UnderlyingLike,
        expiry: str | None = None,
    ) -> OptionChainSnapshot:
        """Fetch and normalize an option chain.

        Args:
            underlying: Object exposing ``symbol``, ``security_id`` and, normally,
                instrument-master ``contracts``.
            expiry: Optional explicit expiry in ``YYYY-MM-DD`` format.

        Returns:
            Normalized ``OptionChainSnapshot``.
        """

        symbol = self._symbol(underlying)
        security_id = self._security_id(underlying)

        if expiry is not None:
            selected_expiry = self._normalize_expiry(expiry)
        else:
            try:
                selected_expiry = self.select_expiry_from_underlying(underlying)
            except OptionChainError as master_error:
                # Compatibility fallback for callers that provide a minimal
                # underlying object without instrument-master contracts.
                logger.warning(
                    "Instrument-master expiry unavailable for %s (%s); "
                    "falling back to Dhan expiry-list API.",
                    symbol,
                    master_error,
                )
                selected_expiry = self.select_expiry(security_id)

        logger.debug(
            "Fetching option chain for %s security_id=%s expiry=%s segment=%s",
            symbol,
            security_id,
            selected_expiry,
            self.underlying_segment,
        )

        response = self.client.get_option_chain(
            security_id,
            selected_expiry,
            self.underlying_segment,
        )

        return self.normalize(
            underlying=underlying,
            expiry=selected_expiry,
            response=response,
        )

    def get_master_expiries(self, underlying: UnderlyingLike) -> list[str]:
        """Return expiries already loaded from the Dhan instrument master.

        ``InstrumentLoader`` attaches derivative contracts to each underlying.
        Reading their expiry values avoids one Dhan expiry-list API request per
        symbol during a normal scan.
        """

        contracts = getattr(underlying, "contracts", None)
        if not contracts:
            raise OptionChainError(
                f"No instrument-master contracts available for {self._symbol(underlying)}"
            )

        expiries: list[str] = []
        seen: set[str] = set()

        for contract in contracts:
            raw_expiry = (
                contract.get("expiry")
                if isinstance(contract, Mapping)
                else getattr(contract, "expiry", None)
            )
            if raw_expiry in (None, ""):
                continue

            try:
                normalized = self._normalize_expiry(raw_expiry)
            except OptionChainError:
                continue

            if normalized not in seen:
                seen.add(normalized)
                expiries.append(normalized)

        expiries.sort(key=date.fromisoformat)

        if not expiries:
            raise OptionChainError(
                f"No valid instrument-master expiries found for {self._symbol(underlying)}"
            )

        return expiries

    def select_expiry_from_underlying(self, underlying: UnderlyingLike) -> str:
        """Select the configured active expiry from instrument-master contracts."""

        expiries = self.get_master_expiries(underlying)
        today = date.today()
        active = [expiry for expiry in expiries if date.fromisoformat(expiry) >= today]
        candidates = active or expiries

        if self.expiry_index >= len(candidates):
            raise OptionChainError(
                f"Expiry index {self.expiry_index} is unavailable for "
                f"{self._symbol(underlying)}; instrument master contains "
                f"{len(candidates)} eligible expiries"
            )

        selected = candidates[self.expiry_index]
        logger.debug(
            "Selected instrument-master expiry for %s: %s (available=%d)",
            self._symbol(underlying),
            selected,
            len(candidates),
        )
        return selected

    def get_expiries(self, underlying: UnderlyingLike | int | str) -> list[str]:
        """Return sorted, unique, valid expiries for an underlying."""

        if isinstance(underlying, (int, str)):
            security_id = self._to_int(underlying, "security_id")
        else:
            security_id = self._security_id(underlying)

        raw = self.client.get_expiries(
            security_id,
            self.underlying_segment,
        )
        values = self._extract_expiry_values(raw)

        expiries: list[str] = []
        seen: set[str] = set()

        for value in values:
            try:
                normalized = self._normalize_expiry(value)
            except OptionChainError:
                continue

            if normalized not in seen:
                seen.add(normalized)
                expiries.append(normalized)

        expiries.sort(key=date.fromisoformat)

        if not expiries:
            raise OptionChainError(
                f"No valid expiries returned for security_id={security_id}"
            )

        return expiries

    def select_expiry(self, security_id: int) -> str:
        """Select the configured active expiry from Dhan's expiry list."""

        expiries = self.get_expiries(security_id)

        today = datetime.now(timezone.utc).date()
        active = [
            expiry
            for expiry in expiries
            if date.fromisoformat(expiry) >= today
        ]
        candidates = active or expiries

        if self.expiry_index >= len(candidates):
            raise OptionChainError(
                f"Expiry index {self.expiry_index} is unavailable for "
                f"security_id={security_id}; received {len(candidates)} expiries"
            )

        return candidates[self.expiry_index]

    def normalize(
        self,
        underlying: UnderlyingLike,
        expiry: str,
        response: Mapping[str, Any],
    ) -> OptionChainSnapshot:
        """Normalize Dhan's response into analytics models."""

        symbol = self._symbol(underlying)
        security_id = self._security_id(underlying)
        expiry = self._normalize_expiry(expiry)

        if not isinstance(response, Mapping):
            raise OptionChainError(
                f"Invalid option-chain response type for {symbol}: "
                f"{type(response).__name__}"
            )

        status = str(response.get("status", "")).strip().lower()
        if status and status != "success":
            raise OptionChainError(
                f"Dhan option-chain request failed for {symbol} {expiry}: "
                f"{dict(response)!r}"
            )

        data = response.get("data")
        if not isinstance(data, Mapping):
            raise OptionChainError(
                f"Invalid option-chain data for {symbol} {expiry}: {data!r}"
            )

        # Some dhanhq SDK versions wrap the actual option-chain payload one or
        # more times inside response-like {"status": ..., "data": ...}
        # dictionaries. Find the nested mapping that really contains "oc".
        data = self._find_option_chain_payload(data)

        nested_status = str(data.get("status", "")).strip().lower()
        if nested_status and nested_status != "success" and "oc" not in data:
            raise OptionChainError(
                f"Dhan option-chain request failed for {symbol} {expiry}: "
                f"{dict(data)!r}"
            )

        raw_chain = data.get("oc")
        if not isinstance(raw_chain, Mapping) or not raw_chain:
            raise OptionChainError(
                f"No strikes returned for {symbol} {expiry}; "
                f"data_keys={list(data.keys())}"
            )

        underlying_ltp = self._number(
            self._first(data, "last_price", "ltp", "underlying_ltp"),
            default=0.0,
        )

        strikes: list[StrikeData] = []

        for raw_strike, raw_entry in raw_chain.items():
            if not isinstance(raw_entry, Mapping):
                continue

            strike = self._number(raw_strike, default=None)
            if strike is None:
                continue

            call = self._normalize_leg(
                payload=raw_entry.get("ce"),
                side=OptionSide.CALL,
                strike=strike,
            )
            put = self._normalize_leg(
                payload=raw_entry.get("pe"),
                side=OptionSide.PUT,
                strike=strike,
            )

            if call is None and put is None:
                continue

            strikes.append(
                StrikeData(
                    strike=float(strike),
                    call=call,
                    put=put,
                )
            )

        strikes.sort(key=lambda item: item.strike)

        if not strikes:
            sample = next(iter(raw_chain.items()), None)
            raise OptionChainError(
                f"No usable strikes parsed for {symbol} {expiry}; "
                f"chain_entries={len(raw_chain)}, sample={sample!r}"
            )

        captured_at = datetime.now(timezone.utc).isoformat().replace(
            "+00:00",
            "Z",
        )

        snapshot = OptionChainSnapshot(
            symbol=symbol,
            underlying_security_id=str(security_id),
            expiry=expiry,
            underlying_ltp=float(underlying_ltp or 0.0),
            captured_at=captured_at,
            strikes=strikes,
        )

        logger.debug(
            "Normalized option chain for %s expiry=%s strikes=%d ltp=%.2f",
            symbol,
            expiry,
            len(strikes),
            snapshot.underlying_ltp,
        )
        return snapshot

    @classmethod
    def _normalize_leg(
        cls,
        *,
        payload: Any,
        side: OptionSide,
        strike: float,
    ) -> OptionLeg | None:
        if not isinstance(payload, Mapping) or not payload:
            return None

        security_id = cls._first(
            payload,
            "security_id",
            "securityId",
            "sid",
        )

        ltp = cls._number(
            cls._first(
                payload,
                "last_price",
                "ltp",
                "lastPrice",
            ),
            default=0.0,
        )
        oi = cls._integer(
            cls._first(
                payload,
                "oi",
                "open_interest",
                "openInterest",
            ),
            default=0,
        )
        volume = cls._integer(
            cls._first(
                payload,
                "volume",
                "traded_volume",
                "tradedVolume",
            ),
            default=0,
        )
        iv = cls._number(
            cls._first(
                payload,
                "implied_volatility",
                "iv",
                "impliedVolatility",
            ),
            default=0.0,
        )

        bid = cls._number(
            cls._first(
                payload,
                "top_bid_price",
                "bid_price",
                "bid",
                "best_bid_price",
            ),
            default=0.0,
        )
        ask = cls._number(
            cls._first(
                payload,
                "top_ask_price",
                "ask_price",
                "ask",
                "best_ask_price",
            ),
            default=0.0,
        )

        return OptionLeg(
            security_id=cls._normalize_id(security_id),
            side=side,
            strike=float(strike),
            ltp=float(ltp or 0.0),
            oi=int(oi),
            volume=int(volume),
            iv=float(iv or 0.0),
            bid=float(bid or 0.0),
            ask=float(ask or 0.0),
        )

    @staticmethod
    def _find_option_chain_payload(root: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return the nested mapping that contains the actual ``oc`` chain."""

        queue: list[Mapping[str, Any]] = [root]
        visited: set[int] = set()

        while queue:
            current = queue.pop(0)
            identity = id(current)

            if identity in visited:
                continue
            visited.add(identity)

            chain = current.get("oc")
            if isinstance(chain, Mapping):
                return current

            # Prefer common response-wrapper fields first.
            nested_data = current.get("data")
            if isinstance(nested_data, Mapping):
                queue.append(nested_data)

            for key, value in current.items():
                if key == "data":
                    continue
                if isinstance(value, Mapping):
                    queue.append(value)

        return root

    @staticmethod
    def _extract_expiry_values(raw: Any) -> Sequence[Any]:
        """Support SDK responses and already-unwrapped expiry lists."""

        if isinstance(raw, (list, tuple)):
            return raw

        if not isinstance(raw, Mapping):
            return ()

        data = raw.get("data")

        if isinstance(data, (list, tuple)):
            return data

        if isinstance(data, Mapping):
            nested = data.get("data")
            if isinstance(nested, (list, tuple)):
                return nested

            for key in ("expiry", "expiries", "expiry_list", "expiryList"):
                value = data.get(key)
                if isinstance(value, (list, tuple)):
                    return value

        for key in ("expiry", "expiries", "expiry_list", "expiryList"):
            value = raw.get(key)
            if isinstance(value, (list, tuple)):
                return value

        return ()

    @staticmethod
    def _symbol(underlying: UnderlyingLike) -> str:
        value = getattr(underlying, "symbol", None)
        symbol = str(value or "").strip().upper()
        if not symbol:
            raise OptionChainError("Underlying symbol is missing")
        return symbol

    @staticmethod
    def _security_id(underlying: UnderlyingLike) -> int:
        for attribute in (
            "security_id",
            "underlying_security_id",
            "equity_security_id",
        ):
            value = getattr(underlying, attribute, None)
            if value not in (None, ""):
                return OptionChainService._to_int(value, attribute)

        raise OptionChainError(
            f"Security ID is missing for "
            f"{getattr(underlying, 'symbol', '<unknown>')}"
        )

    @staticmethod
    def _normalize_expiry(value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()

        text = str(value or "").strip()
        if not text or text.upper() in {"NAN", "NAT", "NONE"}:
            raise OptionChainError("Expiry cannot be blank")

        # Dhan instrument-master files and SDK versions have used a few
        # different date representations. Normalize all supported values to
        # the YYYY-MM-DD format expected by the option-chain endpoint.
        candidates = [text, text[:10]]
        formats = (
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
        )

        for candidate in candidates:
            for fmt in formats:
                try:
                    return datetime.strptime(candidate, fmt).date().isoformat()
                except ValueError:
                    continue

        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError as exc:
            raise OptionChainError(
                f"Invalid expiry value: {value!r}; expected a supported calendar date"
            ) from exc

    @staticmethod
    def _first(payload: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return None

    @staticmethod
    def _number(value: Any, *, default: float | None) -> float | None:
        if value in (None, ""):
            return default
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return default

        if result != result or result in (float("inf"), float("-inf")):
            return default
        return result

    @staticmethod
    def _integer(value: Any, *, default: int) -> int:
        if value in (None, ""):
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _to_int(value: Any, field_name: str) -> int:
        try:
            result = int(float(value))
        except (TypeError, ValueError, OverflowError) as exc:
            raise OptionChainError(
                f"Invalid {field_name}: {value!r}"
            ) from exc

        if result <= 0:
            raise OptionChainError(
                f"{field_name} must be positive; received {result}"
            )
        return result

    @staticmethod
    def _normalize_id(value: Any) -> str:
        if value in (None, ""):
            return ""
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            return str(value).strip()

        if numeric.is_integer():
            return str(int(numeric))
        return str(value).strip()


__all__ = [
    "DhanOptionChainClient",
    "OptionChainError",
    "OptionChainService",
    "UnderlyingLike",
]
