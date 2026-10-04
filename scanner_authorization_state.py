"""Offline-safe helpers for the scanner's market-data authorization latch."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed
    except ValueError:
        return None


def read_json_object(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
        return {}
    except (OSError, ValueError, TypeError):
        return {}


def authorization_failure_is_unresolved(
    runtime_state: Mapping[str, Any],
    validation_state: Mapping[str, Any],
) -> bool:
    """Require a successful explicit market-data validation newer than failure."""

    if str(runtime_state.get("status") or "").upper() != "AUTHORIZATION_FAILED":
        return False

    if str(validation_state.get("status") or "").upper() != "MARKET_DATA_VALIDATED":
        return True

    failed_at = _timestamp(runtime_state.get("updated_at"))
    validated_at = _timestamp(validation_state.get("validated_at"))

    if failed_at is None or validated_at is None:
        return True

    try:
        return validated_at <= failed_at
    except TypeError:
        return True


def scanner_authorization_is_blocked(
    runtime_path: str | Path,
    validation_path: str | Path,
) -> bool:
    return authorization_failure_is_unresolved(
        read_json_object(runtime_path),
        read_json_object(validation_path),
    )
