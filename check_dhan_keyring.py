from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
client_id = os.getenv("DHAN_CLIENT_ID", "").strip()

if not client_id:
    raise SystemExit("FAIL: DHAN_CLIENT_ID is missing from .env")

try:
    import keyring
except ImportError:
    raise SystemExit("FAIL: Python package 'keyring' is not installed. Run: python -m pip install keyring")

service = "CAlphaTrader:DhanTOTP"
try:
    secret = keyring.get_password(service, client_id)
except Exception as exc:
    raise SystemExit(f"FAIL: Windows keyring lookup failed: {type(exc).__name__}: {exc}")

if secret:
    print("PASS: Existing Dhan TOTP secret found in Windows Credential Manager.")
    print(f"Service: {service}")
    print("Secret value: NOT DISPLAYED")
else:
    print("NOT FOUND: No credential matched the expected service + DHAN_CLIENT_ID.")
    print(f"Expected service: {service}")
    print("The secret value was not requested or displayed.")
