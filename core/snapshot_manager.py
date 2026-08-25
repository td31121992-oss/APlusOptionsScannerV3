"""
core/snapshot_manager.py

Snapshot persistence and comparison utilities.

The comparison window defaults to eight hours so scans performed at different
times during the same trading session can still use the most recent snapshot.
The previous 30-minute default caused ``load_previous`` to return ``None`` when
the gap between scans exceeded 30 minutes, leaving every OI change at zero.
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from analytics.enums import OptionSide
from analytics.models import OptionChainSnapshot, OptionLeg, StrikeData
from config import CONFIG
from logger import get_logger


logger = get_logger(__name__)


class SnapshotError(RuntimeError):
    """Raised when a snapshot cannot be saved, loaded, or compared."""


class SnapshotManager:
    """Persist option-chain snapshots and calculate interval changes."""

    DEFAULT_MAX_AGE_MINUTES = 8 * 60
    DEFAULT_MIN_AGE_SECONDS = 1

    def __init__(
        self,
        root: Path | None = None,
        *,
        comparison_max_age_minutes: int | None = None,
        comparison_min_age_seconds: int | None = None,
    ) -> None:
        self.root = Path(
            root or CONFIG.reports.output_dir.parent / "snapshots"
        )
        self.root.mkdir(parents=True, exist_ok=True)

        env_max_age = os.getenv(
            "APLUS_SNAPSHOT_MAX_AGE_MINUTES",
            "",
        ).strip()
        env_min_age = os.getenv(
            "APLUS_SNAPSHOT_MIN_AGE_SECONDS",
            "",
        ).strip()

        self.comparison_max_age_minutes = self._positive_int(
            comparison_max_age_minutes,
            env_max_age,
            self.DEFAULT_MAX_AGE_MINUTES,
            "comparison_max_age_minutes",
        )
        self.comparison_min_age_seconds = self._non_negative_int(
            comparison_min_age_seconds,
            env_min_age,
            self.DEFAULT_MIN_AGE_SECONDS,
            "comparison_min_age_seconds",
        )

    def _folder(
        self,
        snapshot: OptionChainSnapshot,
        *,
        create: bool,
    ) -> Path:
        folder = (
            self.root
            / self._safe_component(snapshot.symbol)
            / self._safe_component(snapshot.expiry)
        )
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        return folder

    def save(self, snapshot: OptionChainSnapshot) -> Path:
        """Atomically save one compressed snapshot."""

        captured_at = self._parse_timestamp(snapshot.captured_at)
        stamp = captured_at.strftime("%Y%m%dT%H%M%S%fZ")
        destination = (
            self._folder(snapshot, create=True)
            / f"{stamp}.json.gz"
        )

        payload = json.dumps(
            snapshot.to_dict(),
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")

        fd, temporary_name = tempfile.mkstemp(
            prefix="snapshot_",
            suffix=".tmp",
            dir=destination.parent,
        )
        os.close(fd)
        temporary_path = Path(temporary_name)

        try:
            with gzip.open(temporary_path, "wb") as handle:
                handle.write(payload)

            os.replace(temporary_path, destination)
            return destination

        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            raise SnapshotError(
                f"Unable to save snapshot for "
                f"{snapshot.symbol} {snapshot.expiry}: {exc}"
            ) from exc

    def load_previous(
        self,
        current: OptionChainSnapshot,
        max_age_minutes: int | None = None,
        min_age_seconds: int | None = None,
    ) -> OptionChainSnapshot | None:
        """
        Load the newest valid snapshot strictly older than ``current``.

        By default, snapshots from the previous eight hours are eligible. This
        covers the complete NSE trading session while excluding an overnight
        snapshot from the prior market day.
        """

        effective_max_age = (
            self.comparison_max_age_minutes
            if max_age_minutes is None
            else int(max_age_minutes)
        )
        effective_min_age = (
            self.comparison_min_age_seconds
            if min_age_seconds is None
            else int(min_age_seconds)
        )

        if effective_max_age <= 0:
            raise ValueError("max_age_minutes must be positive")
        if effective_min_age < 0:
            raise ValueError("min_age_seconds cannot be negative")

        folder = self._folder(current, create=False)
        if not folder.exists():
            logger.debug(
                "No snapshot folder symbol=%s expiry=%s folder=%s",
                current.symbol,
                current.expiry,
                folder,
            )
            return None

        current_time = self._parse_timestamp(current.captured_at)
        minimum_age = timedelta(seconds=effective_min_age)
        maximum_age = timedelta(minutes=effective_max_age)

        selected: OptionChainSnapshot | None = None
        selected_time: datetime | None = None
        selected_path: Path | None = None
        rejected_too_new = 0
        rejected_too_old = 0
        invalid_count = 0

        # File names are timestamp ordered, so reverse sorting usually reaches
        # the newest eligible snapshot first. We still validate captured_at.
        for path in sorted(
            folder.glob("*.json.gz"),
            reverse=True,
        ):
            try:
                previous = self._read_snapshot(path)
                previous_time = self._parse_timestamp(
                    previous.captured_at
                )
            except Exception as exc:
                invalid_count += 1
                logger.warning(
                    "Ignoring invalid snapshot %s: %s",
                    path,
                    exc,
                )
                continue

            if self._normalize_symbol(previous.symbol) != (
                self._normalize_symbol(current.symbol)
            ):
                continue
            if self._normalize_expiry(previous.expiry) != (
                self._normalize_expiry(current.expiry)
            ):
                continue

            age = current_time - previous_time

            # Negative or too-small ages can occur from duplicate timestamps,
            # clock skew, or a file belonging to the current capture.
            if age < minimum_age:
                rejected_too_new += 1
                continue
            if age > maximum_age:
                rejected_too_old += 1
                continue

            if selected_time is None or previous_time > selected_time:
                selected = previous
                selected_time = previous_time
                selected_path = path

        if selected is None:
            logger.warning(
                "No eligible previous snapshot symbol=%s expiry=%s "
                "window=%dmin min_age=%ds too_new=%d too_old=%d invalid=%d",
                current.symbol,
                current.expiry,
                effective_max_age,
                effective_min_age,
                rejected_too_new,
                rejected_too_old,
                invalid_count,
            )
            return None

        age_seconds = (
            current_time - selected_time
        ).total_seconds() if selected_time is not None else 0.0

        logger.debug(
            "Previous snapshot selected symbol=%s expiry=%s "
            "age_seconds=%.1f path=%s",
            current.symbol,
            current.expiry,
            age_seconds,
            selected_path,
        )
        return selected

    def apply_changes(
        self,
        current: OptionChainSnapshot,
        previous: OptionChainSnapshot | None,
    ) -> OptionChainSnapshot:
        """Populate interval OI and premium changes on the current snapshot."""

        # Start from a clean comparison state. This avoids carrying any raw or
        # stale change values supplied by an upstream payload.
        for leg in current.all_legs():
            leg.previous_oi = 0
            leg.previous_close = 0.0
            leg.oi_change = 0
            leg.oi_change_percent = 0.0
            leg.price_change = 0.0
            leg.price_change_percent = 0.0

        if previous is None:
            logger.debug(
                "Snapshot comparison skipped symbol=%s expiry=%s: "
                "no previous snapshot",
                current.symbol,
                current.expiry,
            )
            return current

        if self._normalize_symbol(previous.symbol) != (
            self._normalize_symbol(current.symbol)
        ):
            raise SnapshotError(
                f"Cannot compare symbols "
                f"{previous.symbol!r} and {current.symbol!r}"
            )

        if self._normalize_expiry(previous.expiry) != (
            self._normalize_expiry(current.expiry)
        ):
            raise SnapshotError(
                f"Cannot compare expiries "
                f"{previous.expiry!r} and {current.expiry!r}"
            )

        by_security_id: dict[str, OptionLeg] = {}
        by_strike_side: dict[tuple[str, str], OptionLeg] = {}

        for leg in previous.all_legs():
            security_id = self._normalize_security_id(
                leg.security_id
            )
            if security_id:
                by_security_id[security_id] = leg

            by_strike_side[self._leg_key(leg)] = leg

        matched = 0
        matched_by_security_id = 0
        matched_by_strike_side = 0
        unmatched = 0
        nonzero_oi_changes = 0
        nonzero_price_changes = 0

        for leg in current.all_legs():
            prior: OptionLeg | None = None

            security_id = self._normalize_security_id(
                leg.security_id
            )
            if security_id:
                prior = by_security_id.get(security_id)
                if prior is not None:
                    matched_by_security_id += 1

            if prior is None:
                prior = by_strike_side.get(self._leg_key(leg))
                if prior is not None:
                    matched_by_strike_side += 1

            if prior is None:
                unmatched += 1
                continue

            matched += 1

            current_oi = int(leg.oi or 0)
            prior_oi = int(prior.oi or 0)
            current_ltp = float(leg.ltp or 0.0)
            prior_ltp = float(prior.ltp or 0.0)

            leg.previous_oi = prior_oi
            leg.previous_close = prior_ltp
            leg.oi_change = current_oi - prior_oi
            leg.price_change = current_ltp - prior_ltp

            leg.oi_change_percent = (
                (leg.oi_change / prior_oi) * 100.0
                if prior_oi > 0
                else 0.0
            )
            leg.price_change_percent = (
                (leg.price_change / prior_ltp) * 100.0
                if prior_ltp > 0
                else 0.0
            )

            if leg.oi_change != 0:
                nonzero_oi_changes += 1
            if leg.price_change != 0:
                nonzero_price_changes += 1

        logger.info(
            "Snapshot comparison symbol=%s expiry=%s matched=%d "
            "security_id=%d strike_side=%d unmatched=%d "
            "nonzero_oi=%d nonzero_price=%d",
            current.symbol,
            current.expiry,
            matched,
            matched_by_security_id,
            matched_by_strike_side,
            unmatched,
            nonzero_oi_changes,
            nonzero_price_changes,
        )

        if matched == 0:
            logger.warning(
                "Snapshot comparison matched no option legs "
                "symbol=%s expiry=%s",
                current.symbol,
                current.expiry,
            )

        return current

    def cleanup(self, retention_days: int = 5) -> int:
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")

        cutoff = datetime.now(timezone.utc) - timedelta(
            days=retention_days
        )
        removed = 0

        for path in self.root.rglob("*.json.gz"):
            try:
                snapshot = self._read_snapshot(path)
                captured_at = self._parse_timestamp(
                    snapshot.captured_at
                )
            except Exception:
                try:
                    captured_at = datetime.fromtimestamp(
                        path.stat().st_mtime,
                        timezone.utc,
                    )
                except OSError:
                    continue

            if captured_at >= cutoff:
                continue

            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                logger.warning(
                    "Unable to delete snapshot %s: %s",
                    path,
                    exc,
                )

        return removed

    @classmethod
    def _read_snapshot(
        cls,
        path: Path,
    ) -> OptionChainSnapshot:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                data = json.load(handle)
        except (
            OSError,
            gzip.BadGzipFile,
            json.JSONDecodeError,
        ) as exc:
            raise SnapshotError(
                f"Unable to read snapshot {path}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise SnapshotError(
                f"Snapshot root must be an object: {path}"
            )

        return cls._from_dict(data)

    @classmethod
    def _from_dict(
        cls,
        data: dict[str, Any],
    ) -> OptionChainSnapshot:
        strikes: list[StrikeData] = []

        raw_strikes = data.get("strikes", [])
        if not isinstance(raw_strikes, list):
            raise SnapshotError(
                "Snapshot field 'strikes' must be a list"
            )

        for item in raw_strikes:
            if not isinstance(item, dict):
                continue

            if "strike" not in item:
                logger.warning(
                    "Ignoring snapshot strike without a strike value"
                )
                continue

            call = cls._leg_from_dict(item.get("call"))
            put = cls._leg_from_dict(item.get("put"))

            strikes.append(
                StrikeData(
                    strike=float(item["strike"]),
                    call=call,
                    put=put,
                )
            )

        return OptionChainSnapshot(
            symbol=str(data["symbol"]),
            underlying_security_id=str(
                data["underlying_security_id"]
            ),
            expiry=str(data["expiry"]),
            underlying_ltp=float(
                data.get("underlying_ltp", 0.0)
            ),
            captured_at=str(data["captured_at"]),
            strikes=strikes,
        )

    @staticmethod
    def _leg_from_dict(value: Any) -> OptionLeg | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise SnapshotError(
                "Option leg must be a JSON object"
            )

        payload = dict(value)
        payload["side"] = SnapshotManager._normalize_side(
            payload.get("side")
        )

        # Preserve compatibility with older snapshots missing newer model
        # fields by supplying defaults expected by the current OptionLeg.
        payload.setdefault("iv", 0.0)
        payload.setdefault("bid", 0.0)
        payload.setdefault("ask", 0.0)
        payload.setdefault("previous_oi", 0)
        payload.setdefault("previous_close", 0.0)
        payload.setdefault("oi_change", 0)
        payload.setdefault("oi_change_percent", 0.0)
        payload.setdefault("price_change", 0.0)
        payload.setdefault("price_change_percent", 0.0)

        return OptionLeg(**payload)

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"

        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise SnapshotError(
                f"Invalid snapshot timestamp: {value!r}"
            ) from exc

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _normalize_side(value: Any) -> OptionSide:
        if isinstance(value, OptionSide):
            return value

        text = str(value or "").strip().upper()
        if text in {"CALL", "CE", "OPTIONSIDE.CALL"}:
            return OptionSide.CALL
        if text in {"PUT", "PE", "OPTIONSIDE.PUT"}:
            return OptionSide.PUT

        raise SnapshotError(
            f"Invalid option side in snapshot: {value!r}"
        )

    @staticmethod
    def _normalize_security_id(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        try:
            number = float(text)
        except (TypeError, ValueError):
            return text

        if number.is_integer():
            return str(int(number))
        return text

    @staticmethod
    def _normalize_strike(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value).strip()

        if number.is_integer():
            return str(int(number))
        return f"{number:.8f}".rstrip("0").rstrip(".")

    @staticmethod
    def _leg_key(leg: OptionLeg) -> tuple[str, str]:
        side = SnapshotManager._normalize_side(leg.side)
        return (
            SnapshotManager._normalize_strike(leg.strike),
            side.value,
        )

    @staticmethod
    def _normalize_symbol(value: Any) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _normalize_expiry(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _safe_component(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise SnapshotError("Snapshot path component cannot be blank")

        # Symbols and ISO expiry values should not contain path separators.
        if "/" in text or "\\" in text or text in {".", ".."}:
            raise SnapshotError(
                f"Unsafe snapshot path component: {text!r}"
            )
        return text

    @staticmethod
    def _positive_int(
        explicit: int | None,
        environment_value: str,
        default: int,
        field_name: str,
    ) -> int:
        raw: Any = explicit
        if raw is None and environment_value:
            raw = environment_value
        if raw is None:
            raw = default

        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name} must be an integer"
            ) from exc

        if value <= 0:
            raise ValueError(f"{field_name} must be positive")
        return value

    @staticmethod
    def _non_negative_int(
        explicit: int | None,
        environment_value: str,
        default: int,
        field_name: str,
    ) -> int:
        raw: Any = explicit
        if raw is None and environment_value:
            raw = environment_value
        if raw is None:
            raw = default

        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name} must be an integer"
            ) from exc

        if value < 0:
            raise ValueError(
                f"{field_name} cannot be negative"
            )
        return value


__all__ = ["SnapshotError", "SnapshotManager"]
