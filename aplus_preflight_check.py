from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

print("=" * 60)
print("APlusOptionsScannerV3 PRE-FLIGHT CHECK")
print("PAPER ONLY - THIS SCRIPT DOES NOT PLACE ORDERS")
print("=" * 60)

# ------------------------------------------------------------
# Dhan automatic authentication
# ------------------------------------------------------------
client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
pin = os.getenv("DHAN_PIN", "").strip()

if not client_id:
    raise SystemExit("FAIL: DHAN_CLIENT_ID missing in .env")
if not pin:
    raise SystemExit("FAIL: DHAN_PIN missing in .env")

try:
    from dhan_auth import resolve_access_token
except Exception as exc:
    raise SystemExit(f"FAIL: could not import dhan_auth.py: {type(exc).__name__}: {exc}")

try:
    token = resolve_access_token(
        project_root=PROJECT_ROOT,
        client_id=client_id,
        env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip(),
    )
except Exception as exc:
    raise SystemExit(f"FAIL: Dhan token resolution failed: {type(exc).__name__}: {exc}")

if not token:
    raise SystemExit("FAIL: Dhan token resolver returned an empty token")

print("PASS: Dhan access token resolved automatically.")
print("Token value: NOT DISPLAYED")

try:
    r = requests.get(
        "https://api.dhan.co/v2/profile",
        headers={
            "access-token": token,
            "client-id": client_id,
            "Accept": "application/json",
        },
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, dict):
        raise RuntimeError("profile response is not a JSON object")
    returned_id = str(body.get("dhanClientId") or "")
    if returned_id and returned_id != client_id:
        raise RuntimeError("profile client ID does not match DHAN_CLIENT_ID")

    # Dhan separates token validity from Data API entitlement/validity.
    # A valid /profile response is therefore not enough to start the scanner.
    data_plan = str(body.get("dataPlan") or "").strip().lower()
    if data_plan != "active":
        raise RuntimeError(f"Dhan Data API plan is not Active (dataPlan={body.get('dataPlan')!r})")

    data_validity = str(body.get("dataValidity") or "").strip()
    if data_validity:
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
            try:
                parsed = datetime.strptime(data_validity, fmt).replace(
                    tzinfo=timezone(timedelta(hours=5, minutes=30))
                )
                break
            except ValueError:
                pass
        if parsed is not None and parsed <= datetime.now(timezone.utc):
            raise RuntimeError(f"Dhan Data API validity has expired (dataValidity={data_validity})")

    # Read-only Data API probe. This does not place or modify orders.
    # It intentionally uses a small 5-minute candle request for a stable NSE
    # equity security so a token with profile access but broken Data API
    # authorization is not mistaken for a healthy scanner session.
    probe_day = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30) - timedelta(days=1)).date()
    probe_date = probe_day.isoformat()
    probe = requests.post(
        "https://api.dhan.co/v2/charts/intraday",
        headers={
            "access-token": token,
            "client-id": client_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "securityId": "1333",
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "interval": "5",
            "oi": False,
            "fromDate": probe_date + " 09:15:00",
            "toDate": probe_date + " 15:30:00",
        },
        timeout=12,
    )
    if probe.status_code != 200:
        detail = ""
        try:
            payload = probe.json()
            if isinstance(payload, dict):
                detail = str(payload.get("errorMessage") or payload.get("message") or payload.get("errorCode") or "").strip()
        except Exception:
            pass
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Dhan intraday Data API probe HTTP {probe.status_code}{suffix}")
    probe_body = probe.json()
    if not isinstance(probe_body, dict):
        raise RuntimeError("Dhan intraday Data API probe returned a non-JSON-object response")
except Exception as exc:
    raise SystemExit(f"FAIL: Dhan Data API validation failed: {type(exc).__name__}: {exc}")

print("PASS: Dhan profile validation succeeded.")
print("PASS: Dhan Data API plan/validity validation succeeded.")
print("PASS: Dhan intraday historical Data API probe succeeded (read-only).")
print("PASS: daily manual access-token generation should no longer be required.")

cache_path = PROJECT_ROOT / "data" / "cache" / "dhan_access_token.json"
print(f"Token cache: {cache_path}")

# ------------------------------------------------------------
# Telegram configuration/connection check
# ------------------------------------------------------------
enabled = os.getenv("TELEGRAM_ENABLED", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

if not enabled:
    print("WARN: TELEGRAM_ENABLED is false; trade alerts are disabled.")
elif not bot_token or not chat_id:
    print("WARN: Telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing.")
else:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getMe",
            timeout=10,
        )
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError("Telegram getMe returned failure")
        print("PASS: Telegram bot token is valid.")
    except Exception as exc:
        raise SystemExit(f"FAIL: Telegram bot validation failed: {type(exc).__name__}: {exc}")

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getChat",
            params={"chat_id": chat_id},
            timeout=10,
        )
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError("Telegram getChat returned failure")
        print("PASS: Telegram chat ID is reachable.")
        print("No Telegram test message was sent.")
    except Exception as exc:
        raise SystemExit(f"FAIL: Telegram chat validation failed: {type(exc).__name__}: {exc}")

print("=" * 60)
print("PRE-FLIGHT COMPLETE")
print("Next: run_intraday_movement.bat")
print("=" * 60)
