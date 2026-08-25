"""
dhan_auth.py

Automatic Dhan access-token resolver for APlusOptionsScannerV3.

Priority:
1. Reuse a locally cached token while its Dhan-provided expiry is safely valid.
2. Reuse DHAN_ACCESS_TOKEN from .env if Dhan /profile confirms it is valid.
3. If DHAN_PIN + DHAN_TOTP_SECRET are configured, generate a fresh 24-hour
   token using Dhan's official TOTP endpoint and cache it locally.

This module never places orders.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"
PROFILE_URL = "https://api.dhan.co/v2/profile"
CACHE_SAFETY_SECONDS = 300
KEYRING_SERVICE = "CAlphaTrader:DhanTOTP"
SHARED_ENV_PATH = Path(r"C:\Users\Darpan.bobhate\Desktop\CAlphaTrader\.env")


class DhanAuthError(RuntimeError):
    pass


def _totp(secret: str, *, now: float | None = None) -> str:
    """RFC 6238 SHA-1 TOTP, 6 digits, 30-second step."""
    cleaned = "".join(str(secret).strip().replace(" ", "").split()).upper()
    if not cleaned:
        raise DhanAuthError("DHAN_TOTP_SECRET is empty")
    padding = "=" * ((8 - len(cleaned) % 8) % 8)
    try:
        key = base64.b32decode(cleaned + padding, casefold=True)
    except Exception as exc:
        raise DhanAuthError("DHAN_TOTP_SECRET is not valid Base32") from exc
    counter = int((time.time() if now is None else now) // 30)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def _parse_expiry(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text, text.replace("Z", "+00:00")]
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                # Dhan documents expiryTime as IST for individual access tokens.
                dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
            return dt
        except ValueError:
            pass
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        except ValueError:
            pass
    return None


def _still_valid(expiry: Any, *, safety_seconds: int = CACHE_SAFETY_SECONDS) -> bool:
    dt = _parse_expiry(expiry)
    if dt is None:
        return False
    return dt.astimezone(timezone.utc) > datetime.now(timezone.utc) + timedelta(seconds=safety_seconds)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def _load_cache(path: Path, client_id: str) -> tuple[str, str] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if str(payload.get("dhanClientId") or "") != str(client_id):
        return None
    token = str(payload.get("accessToken") or "").strip()
    expiry = str(payload.get("expiryTime") or "").strip()
    if token and _still_valid(expiry):
        return token, expiry
    return None


def _profile_valid(client_id: str, token: str, *, timeout: float = 8.0) -> tuple[bool, str]:
    if not token:
        return False, ""
    try:
        response = requests.get(
            PROFILE_URL,
            headers={"access-token": token, "client-id": str(client_id), "Accept": "application/json"},
            timeout=timeout,
        )
        if response.status_code != 200:
            return False, ""
        body = response.json()
        if not isinstance(body, dict):
            return False, ""
        returned_id = str(body.get("dhanClientId") or "")
        if returned_id and returned_id != str(client_id):
            return False, ""
        expiry = str(body.get("tokenValidity") or "").strip()
        # A successful profile response proves current validity.  If its
        # validity timestamp parses, also require a small safety margin.
        if expiry and _parse_expiry(expiry):
            return _still_valid(expiry, safety_seconds=60), expiry
        return True, expiry
    except Exception:
        return False, ""


def _keyring_totp_secret(client_id: str) -> str:
    """Read the existing Dhan TOTP secret from the OS credential store.

    Uses the same service name as the CAlphaTrader project so both projects can
    share the same Dhan TOTP enrollment without copying the secret into .env.
    """
    try:
        import keyring
    except ImportError:
        return ""
    try:
        return str(keyring.get_password(KEYRING_SERVICE, str(client_id)) or "").strip()
    except Exception:
        return ""


def _generate(client_id: str, pin: str, totp_secret: str, *, timeout: float = 10.0) -> tuple[str, str]:
    code = _totp(totp_secret)
    try:
        response = requests.post(
            AUTH_URL,
            params={"dhanClientId": str(client_id), "pin": str(pin), "totp": code},
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        raise DhanAuthError(f"Dhan automatic token generation failed: {exc}") from exc

    if not isinstance(body, dict):
        raise DhanAuthError("Dhan automatic token generation returned an invalid response")
    token = str(body.get("accessToken") or "").strip()
    expiry = str(body.get("expiryTime") or "").strip()
    returned_id = str(body.get("dhanClientId") or client_id)
    if returned_id != str(client_id):
        raise DhanAuthError("Dhan token response client ID does not match DHAN_CLIENT_ID")
    if not token:
        # Do not include body: it can contain sensitive information.
        raise DhanAuthError("Dhan automatic token generation returned no accessToken")
    return token, expiry


def _read_shared_env_token(client_id: str) -> str:
    """Read CAlphaTrader's current token without modifying either project."""
    if not SHARED_ENV_PATH.is_file():
        return ""
    values = {}
    for raw in SHARED_ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in {"DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN"}:
            values[key] = value.strip().strip('"').strip("'")
    shared_id = values.get("DHAN_CLIENT_ID", "").strip()
    if shared_id and shared_id != str(client_id):
        raise DhanAuthError("CAlphaTrader shared token belongs to a different DHAN_CLIENT_ID")
    return values.get("DHAN_ACCESS_TOKEN", "").strip()


def resolve_access_token(*, project_root: Path, client_id: str, env_token: str = "") -> str:
    """Use CAlphaTrader as token authority; never generate a competing APlus token."""
    client_id = str(client_id or "").strip()
    if not client_id:
        raise DhanAuthError("DHAN_CLIENT_ID is missing in .env")

    cache_path = Path(project_root) / "data" / "cache" / "dhan_access_token.json"

    shared_token = _read_shared_env_token(client_id)
    if shared_token:
        valid, expiry = _profile_valid(client_id, shared_token)
        if valid:
            if expiry:
                _atomic_json(cache_path, {
                    "dhanClientId": client_id,
                    "accessToken": shared_token,
                    "expiryTime": expiry,
                    "source": "calphatrader_shared_env",
                    "cachedAt": datetime.now(timezone.utc).isoformat(),
                })
            return shared_token
        raise DhanAuthError(
            "CAlphaTrader shared DHAN_ACCESS_TOKEN failed Dhan /profile validation. "
            "APlus did NOT generate a replacement token."
        )

    env_token = str(env_token or "").strip()
    if env_token:
        valid, expiry = _profile_valid(client_id, env_token)
        if valid:
            if expiry:
                _atomic_json(cache_path, {
                    "dhanClientId": client_id,
                    "accessToken": env_token,
                    "expiryTime": expiry,
                    "source": "aplus_env_validated_fallback",
                    "cachedAt": datetime.now(timezone.utc).isoformat(),
                })
            return env_token

    cached = _load_cache(cache_path, client_id)
    if cached:
        valid, _ = _profile_valid(client_id, cached[0])
        if valid:
            return cached[0]

    raise DhanAuthError(
        "No valid shared Dhan token is available. APlus automatic token generation "
        "is disabled to protect CAlphaTrader. Refresh through CAlphaTrader and retry."
    )


__all__ = ["DhanAuthError", "resolve_access_token"]
