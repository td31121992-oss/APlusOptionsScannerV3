"""Who is using the shared Upstox allowance (500 a minute / 2000 per 30 min for the whole token) right now?   python upstox_budget_status.py"""
import json

from core.upstox_client import SHARED_CAPS, _SharedLedger

if __name__ == "__main__":
    u = _SharedLedger().usage()
    print(json.dumps({**u, "caps_30min_per_minute": SHARED_CAPS}, indent=1))
