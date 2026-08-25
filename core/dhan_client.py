"""
=========================================================
APlus Options Scanner V2
Dhan API Client
=========================================================

Thin, retrying wrapper around the dhanhq SDK for read calls (expiry list,
option chain, quotes), plus a direct REST call for order placement since
trade_engine.py builds a payload matching Dhan's raw v2 order schema.

Constructed with just the ``dhan`` section of AppConfig, e.g.:

    client = DhanClient(config.dhan)

Reliability features
---------------------
- Connection pooling sized for the scanner's worker count, so concurrent
  threads reuse warm HTTPS connections instead of renegotiating TLS per call.
- Exponential backoff with jitter on every retry path (SDK calls and raw
  REST order placement), capped by a configurable ceiling.
- Blank/empty response detection: Dhan occasionally returns `None`, `{}`,
  or a body with no `status` key under load -- these are treated as a
  distinct, longer-backoff failure mode rather than a generic exception,
  since they usually mean "you are being throttled" rather than "this
  request is invalid".
- All new tunables are read via getattr(..., default) so this module keeps
  working even if config.py hasn't been updated yet. See the bottom of this
  file for the full list of optional DhanConfig fields it will use.
=========================================================
"""
from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime
from typing import Any, Mapping, Sequence

import requests
from dhanhq import DhanContext, dhanhq
from requests.adapters import HTTPAdapter

from config import DhanConfig
from logger import get_logger

logger = get_logger(__name__)


class DhanClientError(RuntimeError):
    """Raised when a Dhan API call fails after all retries are exhausted."""


class _BlankResponseError(DhanClientError):
    """Internal marker: the API returned an empty/blank body (likely throttled)."""


class DhanClient:
    def __init__(self, dhan_config: DhanConfig) -> None:
        self.config = dhan_config

        logger.info("Connecting to Dhan (client_id=%s)", dhan_config.client_id)

        self._context = DhanContext(dhan_config.client_id, dhan_config.access_token)
        self._client = dhanhq(self._context)

        # ------------------------------------------------
        # Connection pooling
        # ------------------------------------------------
        # Sized off the scanner's worker count where possible so each thread
        # can hold a warm connection without exhausting the pool and falling
        # back to serialized connection creation. Falls back to sane
        # defaults if the config hasn't been extended with these fields yet.
        pool_connections = getattr(dhan_config, "pool_connections", 10)
        pool_maxsize = getattr(dhan_config, "pool_maxsize", 20)

        self._session = requests.Session()
        self._session.headers.update(
            {
                "access-token": dhan_config.access_token,
                "client-id": dhan_config.client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": dhan_config.user_agent,
            }
        )

        # We do our own retry/backoff (with blank-response handling and
        # jitter) above this, so the adapter itself does not retry --
        # doing so in both places would compound backoff unpredictably.
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=0,
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

        # NOTE on thread-safety: requests.Session is safe to share across
        # threads for making concurrent requests (each request gets its own
        # connection from the pool); what is *not* safe is mutating
        # session-level state (headers, adapters) after startup from
        # multiple threads. This client only mutates that state here, in
        # __init__, before any worker threads exist, so no additional
        # locking is needed around request calls themselves.
        self._session_lock = threading.Lock()

        # Dhan enforces per-endpoint rate limits (option-chain/expiry-list is
        # documented at roughly 1 request per 3 seconds). Without throttling,
        # scanning many symbols back-to-back gets every call past the first
        # one or two rejected with a blank {"status": "failure", ...} body.
        self._rate_lock = threading.Lock()
        self._last_call_at: dict[str, float] = {}

        logger.info(
            "Connected to Dhan successfully (pool_connections=%d, pool_maxsize=%d).",
            pool_connections,
            pool_maxsize,
        )

    # ----------------------------------------------------
    # Rate limiting
    # ----------------------------------------------------

    def _throttle(self, bucket: str, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            return
        min_interval = 1.0 / requests_per_second
        with self._rate_lock:
            now = time.monotonic()
            last = self._last_call_at.get(bucket, 0.0)
            wait = min_interval - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._last_call_at[bucket] = time.monotonic()

    # ----------------------------------------------------
    # Backoff
    # ----------------------------------------------------

    def _backoff_seconds(self, attempt: int, *, blank_response: bool = False) -> float:
        """Exponential backoff with jitter, capped at a configurable ceiling.

        `blank_response=True` applies an extra multiplier, since a blank
        body from Dhan is usually a throttling signal and tends to clear up
        faster with a longer cool-down than a generic transient error.
        """
        base = self.config.retry_backoff_seconds
        max_backoff = getattr(self.config, "retry_backoff_max_seconds", base * 20)
        multiplier = getattr(self.config, "blank_response_backoff_multiplier", 2.0) if blank_response else 1.0

        backoff = min(max_backoff, base * (2 ** (attempt - 1))) * multiplier
        backoff = min(backoff, max_backoff * multiplier)

        jitter_ratio = getattr(self.config, "retry_jitter_ratio", 0.25)
        jitter = random.uniform(0, backoff * jitter_ratio)
        return backoff + jitter

    @staticmethod
    def _is_blank(response: Any) -> bool:
        """True for None, empty dict/string, or a dict with neither 'status'
        nor 'data' -- the shapes Dhan returns when a call is throttled/dropped
        rather than genuinely rejected."""
        if response is None:
            return True
        if isinstance(response, str):
            return not response.strip()
        if isinstance(response, dict):
            if not response:
                return True
            return "status" not in response and "data" not in response
        return False

    # ----------------------------------------------------
    # Internal retry wrapper for SDK calls
    # ----------------------------------------------------

    def _call(
        self,
        func: Any,
        *args: Any,
        rate_bucket: str | None = None,
        requests_per_second: float = 0.0,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        was_blank = False

        for attempt in range(1, self.config.max_retries + 2):
            if rate_bucket:
                self._throttle(rate_bucket, requests_per_second)
            try:
                response = func(*args)
            except Exception as exc:  # noqa: BLE001 - retried below, re-raised at the end
                last_error = exc
                was_blank = False
                logger.warning(
                    "Dhan API attempt %d/%d failed (bucket=%s): %s",
                    attempt,
                    self.config.max_retries + 1,
                    rate_bucket or "-",
                    exc,
                )
            else:
                if self._is_blank(response):
                    was_blank = True
                    last_error = _BlankResponseError(
                        f"Dhan API returned a blank/empty response (bucket={rate_bucket or '-'}), "
                        "likely throttled"
                    )
                    logger.warning(
                        "Dhan API attempt %d/%d got a BLANK response (bucket=%s) -- "
                        "treating as throttling, backing off harder",
                        attempt,
                        self.config.max_retries + 1,
                        rate_bucket or "-",
                    )
                elif isinstance(response, dict) and response.get("status") == "success":
                    return response
                else:
                    was_blank = False
                    last_error = DhanClientError(
                        f"Dhan API returned a non-success response (bucket={rate_bucket or '-'}): {response!r}"
                    )
                    logger.warning(
                        "Dhan API attempt %d/%d returned failure (bucket=%s): %s",
                        attempt,
                        self.config.max_retries + 1,
                        rate_bucket or "-",
                        response,
                    )

            if attempt <= self.config.max_retries:
                delay = self._backoff_seconds(attempt, blank_response=was_blank)
                logger.debug("Backing off %.2fs before retry attempt %d", delay, attempt + 1)
                time.sleep(delay)

        raise DhanClientError(str(last_error) if last_error else "Dhan API call failed")

    # ----------------------------------------------------
    # Expiry list
    # ----------------------------------------------------

    def get_expiry_list(self, security_id: str, segment: str) -> list[str]:
        """Return the available expiries for an underlying security."""

        response = self._call(
            self._client.expiry_list,
            int(security_id),
            segment,
            rate_bucket="option_chain",
            requests_per_second=self.config.option_chain_requests_per_second,
        )

        data = response.get("data", {})
        if isinstance(data, dict):
            return list(data.get("data", []))
        if isinstance(data, list):
            return list(data)
        return []

    def get_expiries(self, security_id: int, segment: str) -> list[str]:
        """Compatibility alias used by core.option_chain.OptionChainService."""

        return self.get_expiry_list(str(security_id), segment)

    # ----------------------------------------------------
    # Option chain
    # ----------------------------------------------------

    def get_option_chain(self, security_id: str, expiry: str, segment: str) -> dict[str, Any]:
        # NOTE: the underlying SDK call takes (security_id, segment, expiry) --
        # reordered here to match how option_chain.py calls this wrapper.
        return self._call(
            self._client.option_chain,
            int(security_id),
            segment,
            expiry,
            rate_bucket="option_chain",
            requests_per_second=self.config.option_chain_requests_per_second,
        )

    # ----------------------------------------------------
    # Market quote (best-effort; not guaranteed on every SDK version)
    # ----------------------------------------------------

    def get_quote(self, security_id: str, segment: str) -> dict[str, Any] | None:
        if not hasattr(self._client, "market_quote"):
            logger.warning("market_quote() is not supported by the installed dhanhq SDK.")
            return None
        return self._call(
            self._client.market_quote,
            int(security_id),
            segment,
            rate_bucket="market_quote",
            requests_per_second=self.config.market_quote_requests_per_second,
        )

    # ----------------------------------------------------
    # Direct REST data APIs used by Opening Momentum Scanner
    # ----------------------------------------------------

    def _post_data_api(
        self,
        endpoint: str,
        payload: Mapping[str, Any],
        *,
        rate_bucket: str,
        requests_per_second: float,
        allow_direct_payload: bool = False,
    ) -> dict[str, Any]:
        """POST to a Dhan data endpoint with the same retry discipline.

        Market Quote returns ``{"status": "success", "data": ...}``.
        Historical candle endpoints can return the candle arrays directly,
        without a top-level status field, so ``allow_direct_payload`` accepts
        that documented response shape after validating it is non-empty.
        """

        url = (
            f"{self.config.api_base_url.rstrip('/')}/"
            f"{endpoint.lstrip('/')}"
        )
        last_error: Exception | None = None
        was_blank = False

        for attempt in range(1, self.config.max_retries + 2):
            self._throttle(rate_bucket, requests_per_second)

            try:
                response = self._session.post(
                    url,
                    json=dict(payload),
                    timeout=(
                        self.config.connect_timeout_seconds,
                        self.config.read_timeout_seconds,
                    ),
                    verify=self.config.verify_tls,
                )
                response.raise_for_status()
                body = response.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                was_blank = False
                logger.warning(
                    "Dhan REST data attempt %d/%d failed "
                    "(bucket=%s endpoint=%s): %s",
                    attempt,
                    self.config.max_retries + 1,
                    rate_bucket,
                    endpoint,
                    exc,
                )
            else:
                direct_payload = (
                    allow_direct_payload
                    and isinstance(body, dict)
                    and all(
                        key in body
                        for key in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "timestamp",
                        )
                    )
                )
                if direct_payload:
                    return body
                if self._is_blank(body):
                    was_blank = True
                    last_error = _BlankResponseError(
                        "Dhan REST data API returned a blank response "
                        f"(bucket={rate_bucket}, endpoint={endpoint})"
                    )
                    logger.warning(
                        "Dhan REST data attempt %d/%d got a BLANK "
                        "response (bucket=%s endpoint=%s)",
                        attempt,
                        self.config.max_retries + 1,
                        rate_bucket,
                        endpoint,
                    )
                elif (
                    isinstance(body, dict)
                    and body.get("status") == "success"
                ):
                    return body
                else:
                    was_blank = False
                    last_error = DhanClientError(
                        "Dhan REST data API returned a non-success "
                        f"response (bucket={rate_bucket}, "
                        f"endpoint={endpoint}): {body!r}"
                    )
                    logger.warning(
                        "Dhan REST data attempt %d/%d returned failure "
                        "(bucket=%s endpoint=%s): %s",
                        attempt,
                        self.config.max_retries + 1,
                        rate_bucket,
                        endpoint,
                        body,
                    )

            if attempt <= self.config.max_retries:
                time.sleep(
                    self._backoff_seconds(
                        attempt,
                        blank_response=was_blank,
                    )
                )

        raise DhanClientError(
            str(last_error)
            if last_error
            else f"Dhan REST data call failed: {endpoint}"
        )

    def get_market_quotes(
        self,
        instruments: Mapping[str, Sequence[str | int]],
        *,
        mode: str = "quote",
    ) -> dict[str, dict[str, Any]]:
        """Fetch up to the configured batch size per Market Quote request.

        ``mode`` can be ``ltp``, ``ohlc`` or ``quote``. Returned data is
        normalised to ``{exchange_segment: {security_id: payload}}``.
        """

        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in {"ltp", "ohlc", "quote"}:
            raise ValueError("Market Quote mode must be ltp, ohlc or quote")

        batches = self._instrument_batches(
            instruments,
            max_batch_size=getattr(
                self.config,
                "market_quote_batch_size",
                1000,
            ),
        )
        merged: dict[str, dict[str, Any]] = {}

        for batch in batches:
            response = self._post_data_api(
                f"marketfeed/{normalized_mode}",
                batch,
                rate_bucket="market_quote",
                requests_per_second=(
                    self.config.market_quote_requests_per_second
                ),
            )
            data = response.get("data", {})
            if not isinstance(data, Mapping):
                raise DhanClientError(
                    "Market Quote response has no data mapping"
                )

            for segment, segment_payload in data.items():
                if not isinstance(segment_payload, Mapping):
                    continue
                target = merged.setdefault(str(segment), {})
                for security_id, item in segment_payload.items():
                    if isinstance(item, Mapping):
                        target[str(security_id)] = dict(item)

        return merged

    @staticmethod
    def _instrument_batches(
        instruments: Mapping[str, Sequence[str | int]],
        *,
        max_batch_size: int,
    ) -> list[dict[str, list[int]]]:
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be at least 1")

        flattened: list[tuple[str, int]] = []
        for raw_segment, raw_ids in instruments.items():
            segment = str(raw_segment).strip().upper()
            if not segment:
                continue
            for raw_id in raw_ids:
                try:
                    security_id = int(str(raw_id).strip())
                except (TypeError, ValueError):
                    continue
                if security_id > 0:
                    flattened.append((segment, security_id))

        if not flattened:
            raise ValueError("No valid instruments supplied")

        batches: list[dict[str, list[int]]] = []
        for start in range(0, len(flattened), max_batch_size):
            batch: dict[str, list[int]] = {}
            for segment, security_id in flattened[
                start : start + max_batch_size
            ]:
                batch.setdefault(segment, []).append(security_id)
            batches.append(batch)
        return batches

    def get_intraday_candles(
        self,
        *,
        security_id: str | int,
        segment: str,
        instrument: str,
        interval: int,
        from_datetime: datetime,
        to_datetime: datetime,
        oi: bool = False,
    ) -> dict[str, list[Any]]:
        """Fetch documented minute candles from ``/charts/intraday``."""

        if interval not in {1, 5, 15, 25, 60}:
            raise ValueError(
                "Intraday interval must be one of 1, 5, 15, 25 or 60"
            )
        if to_datetime <= from_datetime:
            raise ValueError("to_datetime must be after from_datetime")

        payload = {
            "securityId": str(int(security_id)),
            "exchangeSegment": str(segment).strip().upper(),
            "instrument": str(instrument).strip().upper(),
            "interval": str(interval),
            "oi": bool(oi),
            "fromDate": from_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": to_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        }
        response = self._post_data_api(
            "charts/intraday",
            payload,
            rate_bucket="historical",
            requests_per_second=getattr(
                self.config,
                "historical_requests_per_second",
                4.0,
            ),
            allow_direct_payload=True,
        )

        raw_data: Any = response
        if (
            isinstance(response.get("data"), Mapping)
            and "open" not in response
        ):
            raw_data = response["data"]
        if not isinstance(raw_data, Mapping):
            raise DhanClientError(
                "Intraday historical response is not a mapping"
            )

        required = (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "timestamp",
        )
        missing = [
            key
            for key in required
            if not isinstance(raw_data.get(key), Sequence)
            or isinstance(raw_data.get(key), (str, bytes))
        ]
        if missing:
            raise DhanClientError(
                "Intraday historical response is missing arrays: "
                f"{missing}"
            )

        size = min(len(raw_data[key]) for key in required)
        return {
            key: list(raw_data.get(key, []))[:size]
            for key in (
                *required,
                "open_interest",
            )
            if isinstance(raw_data.get(key), Sequence)
            and not isinstance(raw_data.get(key), (str, bytes))
        }

    # ----------------------------------------------------
    # Non-trading account APIs used by safety gates
    # ----------------------------------------------------

    def _get_trading_api(
        self,
        endpoint: str,
        *,
        rate_bucket: str = "non_trading",
        requests_per_second: float = 10.0,
    ) -> Any:
        """GET a Dhan trading API endpoint with retry/backoff.

        Fund-limit returns a direct mapping and positions returns a direct list,
        so this helper intentionally accepts both documented response shapes.
        """

        url = (
            f"{self.config.api_base_url.rstrip('/')}/"
            f"{endpoint.lstrip('/')}"
        )
        last_error: Exception | None = None
        was_blank = False

        for attempt in range(1, self.config.max_retries + 2):
            self._throttle(rate_bucket, requests_per_second)
            try:
                response = self._session.get(
                    url,
                    timeout=(
                        self.config.connect_timeout_seconds,
                        self.config.read_timeout_seconds,
                    ),
                    verify=self.config.verify_tls,
                )
                response.raise_for_status()
                body = response.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                was_blank = False
                logger.warning(
                    "Dhan GET attempt %d/%d failed "
                    "(bucket=%s endpoint=%s): %s",
                    attempt,
                    self.config.max_retries + 1,
                    rate_bucket,
                    endpoint,
                    exc,
                )
            else:
                if self._is_blank(body):
                    was_blank = True
                    last_error = _BlankResponseError(
                        "Dhan GET API returned a blank response "
                        f"(bucket={rate_bucket}, endpoint={endpoint})"
                    )
                elif isinstance(body, (dict, list)):
                    if (
                        isinstance(body, dict)
                        and body.get("status") == "failure"
                    ):
                        was_blank = False
                        last_error = DhanClientError(
                            "Dhan GET API returned failure "
                            f"(endpoint={endpoint}): {body!r}"
                        )
                    else:
                        return body
                else:
                    was_blank = False
                    last_error = DhanClientError(
                        "Dhan GET API returned an unsupported response "
                        f"(endpoint={endpoint}): {type(body).__name__}"
                    )

            if attempt <= self.config.max_retries:
                time.sleep(
                    self._backoff_seconds(
                        attempt,
                        blank_response=was_blank,
                    )
                )

        raise DhanClientError(
            str(last_error)
            if last_error
            else f"Dhan GET call failed: {endpoint}"
        )

    def get_fund_limits(self) -> dict[str, Any]:
        """Return available balance, SOD limit and utilised amount."""

        response = self._get_trading_api("fundlimit")
        if not isinstance(response, Mapping):
            raise DhanClientError("Fund-limit response is not a mapping")
        return dict(response)

    def get_positions(self) -> list[dict[str, Any]]:
        """Return all current-day and carry-forward open positions."""

        response = self._get_trading_api("positions")
        if not isinstance(response, Sequence) or isinstance(
            response, (str, bytes)
        ):
            raise DhanClientError("Positions response is not a list")
        return [dict(item) for item in response if isinstance(item, Mapping)]

    # ----------------------------------------------------
    # Order placement
    # ----------------------------------------------------

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.api_base_url.rstrip('/')}/orders"
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_retries + 2):
            try:
                response = self._session.post(
                    url,
                    json=payload,
                    timeout=(self.config.connect_timeout_seconds, self.config.read_timeout_seconds),
                    verify=self.config.verify_tls,
                )
                response.raise_for_status()

                body_text = response.text
                if self._is_blank(body_text):
                    last_error = _BlankResponseError(
                        "Order placement returned a blank body despite a 2xx status "
                        "-- likely throttled or dropped"
                    )
                    logger.warning(
                        "Order placement attempt %d/%d got a BLANK 2xx body -- backing off harder",
                        attempt,
                        self.config.max_retries + 1,
                    )
                    if attempt <= self.config.max_retries:
                        time.sleep(self._backoff_seconds(attempt, blank_response=True))
                    continue

                return response.json()
            except Exception as exc:  # noqa: BLE001 - retried below, re-raised at the end
                last_error = exc
                logger.warning(
                    "Order placement attempt %d/%d failed: %s",
                    attempt,
                    self.config.max_retries + 1,
                    exc,
                )
                if attempt <= self.config.max_retries:
                    time.sleep(self._backoff_seconds(attempt))

        raise DhanClientError(f"Order placement failed: {last_error}")

    # ----------------------------------------------------
    # Health check
    # ----------------------------------------------------

    def test_connection(self) -> bool:
        try:
            response = self._client.get_fund_limits()
            ok = isinstance(response, dict) and response.get("status") == "success"
            if ok:
                logger.info("Dhan authentication OK.")
            elif self._is_blank(response):
                logger.error("Dhan authentication check got a blank response: %r", response)
            else:
                logger.error("Dhan authentication failed: %s", response)
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("Dhan authentication failed: %s", exc)
            return False

    # ----------------------------------------------------
    # Cleanup
    # ----------------------------------------------------

    def close(self) -> None:
        with self._session_lock:
            self._session.close()

    def __enter__(self) -> "DhanClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


__all__ = ["DhanClient", "DhanClientError"]


# =========================================================
# New optional DhanConfig fields this module will pick up
# (all are optional -- getattr(..., default) is used so nothing
# breaks if config.py isn't updated):
#
#   pool_connections: int = 10                    # HTTPAdapter pool_connections
#   pool_maxsize: int = 20                         # HTTPAdapter pool_maxsize
#                                                   #   (set >= scanner max_workers)
#   retry_backoff_max_seconds: float = base * 20   # ceiling for exponential backoff
#   retry_jitter_ratio: float = 0.25               # jitter as a fraction of the
#                                                   #   computed backoff (0-1)
#   historical_requests_per_second: float = 4.0    # intraday candle API throttle
#   market_quote_batch_size: int = 1000            # max instruments/request
#   blank_response_backoff_multiplier: float = 2.0 # extra backoff multiplier
#                                                   #   applied on blank/empty
#                                                   #   Dhan responses
# =========================================================

# =====================================================================
# APLUS_DHAN_429_RELIABILITY_V2
# Infrastructure-only reliability layer.
# =====================================================================
if not getattr(DhanClient, "_aplus_429_reliability_v2_installed", False):
    import threading as _aplus_threading
    import time as _aplus_time

    _aplus_original_throttle_v2 = DhanClient._throttle
    _aplus_original_post_data_api_v2 = DhanClient._post_data_api

    def _aplus_reliability_throttle_v2(self, bucket, requests_per_second):
        bucket_name = str(bucket or "")
        try:
            requested_rps = float(requests_per_second)
        except Exception:
            requested_rps = 0.0

        if bucket_name == "market_quote":
            safe_rps = 0.30
            requested_rps = safe_rps if requested_rps <= 0 else min(requested_rps, safe_rps)
        elif bucket_name == "historical":
            safe_rps = 1.50
            requested_rps = safe_rps if requested_rps <= 0 else min(requested_rps, safe_rps)

        _aplus_original_throttle_v2(self, bucket_name, requested_rps)

        lock = getattr(self, "_aplus_data_global_lock_v2", None)
        if lock is None:
            lock = _aplus_threading.Lock()
            self._aplus_data_global_lock_v2 = lock
            self._aplus_data_global_last_v2 = 0.0

        with lock:
            now = _aplus_time.monotonic()
            last = float(getattr(self, "_aplus_data_global_last_v2", 0.0))
            global_gap = 0.45
            wait = global_gap - (now - last)
            if wait > 0:
                _aplus_time.sleep(wait)
            self._aplus_data_global_last_v2 = _aplus_time.monotonic()

    def _aplus_post_data_api_v2(self, *args, **kwargs):
        try:
            return _aplus_original_post_data_api_v2(self, *args, **kwargs)
        except Exception as exc:
            text = str(exc)
            if "429" in text or "Too Many Requests" in text:
                endpoint = args[0] if args else kwargs.get("endpoint", "")
                logger.warning(
                    "APLUS_DHAN_429_RELIABILITY exhausted_429 endpoint=%s cooldown=10s; caller may skip this cycle safely",
                    endpoint,
                )
                _aplus_time.sleep(10.0)
            raise

    DhanClient._throttle = _aplus_reliability_throttle_v2
    DhanClient._post_data_api = _aplus_post_data_api_v2
    DhanClient._aplus_429_reliability_v2_installed = True
