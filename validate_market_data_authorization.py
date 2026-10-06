"""Explicit read-only market-data validation for the scanner authorization latch.

Makes ONE read-only LTP request. Only when it returns a positive price does it
write market_data_authorization_validation.json, which lets the scanner start
again after an AUTHORIZATION_FAILED stop. It never places or modifies orders
and never prints the access token.

Usage:  python validate_market_data_authorization.py
Exit:   0 validated, 1 not validated (latch left untouched)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent
VALIDATION_PATH = PROJECT_ROOT / "data" / "intraday_movement" / "market_data_authorization_validation.json"
PROBE_SEGMENT = "NSE_EQ"
PROBE_SECURITY_ID = "2885"
LTP_URL = "https://api.dhan.co/v2/marketfeed/ltp"


def positive_ltp(body: Any, segment: str = PROBE_SEGMENT, security_id: str = PROBE_SECURITY_ID) -> bool:
    try:
        quote = body["data"][segment][str(security_id)]
        return float(quote.get("last_price")) > 0
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def fetch_ltp(token: str, client_id: str) -> Mapping[str, Any]:
    import requests

    response = requests.post(
        LTP_URL,
        headers={
            "access-token": token,
            "client-id": client_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={PROBE_SEGMENT: [int(PROBE_SECURITY_ID)]},
        timeout=12,
    )
    response.raise_for_status()
    return response.json()


def validate_and_record(
    token: str,
    client_id: str,
    validation_path: Path = VALIDATION_PATH,
    fetch: Callable[[str, str], Mapping[str, Any]] = fetch_ltp,
    now: datetime | None = None,
) -> bool:
    """Return True and write the validation file only if the probe has a positive LTP."""
    try:
        body = fetch(token, client_id)
    except Exception as exc:  # noqa: BLE001 - report the type only, never the token
        print(f"NOT VALIDATED: probe failed ({type(exc).__name__})")
        return False
    if not positive_ltp(body):
        print("NOT VALIDATED: probe returned no positive LTP")
        return False

    payload = {
        "status": "MARKET_DATA_VALIDATED",
        "validated_at": (now or datetime.now(IST)).isoformat(),
        "segment": PROBE_SEGMENT,
        "security_id": PROBE_SECURITY_ID,
        "evidence": "ONE_READ_ONLY_QUOTE_WITH_POSITIVE_LTP",
    }
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = validation_path.with_suffix(validation_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, validation_path)
    print("VALIDATED: market-data authorization confirmed")
    return True


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
    if not client_id:
        print("NOT VALIDATED: DHAN_CLIENT_ID missing in .env")
        return 1
    try:
        from dhan_auth import resolve_access_token

        token = resolve_access_token(
            project_root=PROJECT_ROOT,
            client_id=client_id,
            env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip(),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"NOT VALIDATED: token resolution failed ({type(exc).__name__})")
        return 1
    if not token:
        print("NOT VALIDATED: empty token")
        return 1
    return 0 if validate_and_record(token, client_id) else 1


if __name__ == "__main__":
    sys.exit(main())
