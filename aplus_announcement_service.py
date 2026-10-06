"""24x7 NSE announcement listener (runs independently of the scanner and of market hours).

Polls every 5 minutes (30 minutes between 00:00 and 06:00), writes a heartbeat to
data/news_intelligence/announcement_health.json, and never exits on a failure.
A localhost socket lock guarantees a single instance. Read-only against NSE.

    python aplus_announcement_service.py            # run forever
    python aplus_announcement_service.py --once     # one poll, print result
    python aplus_announcement_service.py --dry-run  # one poll, nothing stored or sent
"""

from __future__ import annotations

import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import announcement_feed as af

LOCK_PORT = 8795
LOG = af.ROOT / "data" / "logs" / "announcement_service.log"


def log(message: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
    except OSError:
        pass


def interval_seconds(now: datetime) -> int:
    return 1800 if now.hour < 6 else 300


def heartbeat(status: str, detail: dict | None = None) -> None:
    payload = {"service": "APlus Announcement Service", "updated_at": datetime.now(af.IST).isoformat(timespec="seconds"),
               "status": status, **(detail or {})}
    try:
        af._atomic(af.HEALTH, json.dumps(payload))
    except OSError:
        pass


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": af.UA, "Accept": "application/json, */*"})
    return s


def main() -> int:
    once = "--once" in sys.argv
    dry = "--dry-run" in sys.argv
    lock = None
    if not (once or dry):
        lock = socket.socket()
        try:
            lock.bind(("127.0.0.1", LOCK_PORT))
        except OSError:
            print("another announcement service instance is already running")
            return 0
        log("service started")
    failures = 0
    while True:
        now = datetime.now(af.IST)
        try:
            result = af.poll_once(make_session(), now, dry_run=dry)
            failures = 0
            heartbeat("ok", result)
            log(f"poll ok {result}")
            if once or dry:
                print(json.dumps(result))
                return 0
        except Exception as exc:  # noqa: BLE001 - never exit the 24x7 loop
            failures += 1
            heartbeat("error", {"error": f"{type(exc).__name__}: {exc}", "consecutive_failures": failures})
            log(f"poll FAILED ({failures}): {type(exc).__name__}: {exc}")
            if once or dry:
                print(f"FAILED: {type(exc).__name__}: {exc}")
                return 1
        time.sleep(min(interval_seconds(now) * (1 + min(failures, 3)), 1800) if failures else interval_seconds(now))


if __name__ == "__main__":
    raise SystemExit(main())
