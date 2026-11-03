"""Post-open check for the scanner's market-data authorization latch (run by the scheduled task APlus_Post_Open_Latch_Check, every 2 minutes 09:16-10:30).

A single transient 401 at the open makes the scanner latch AUTHORIZATION_FAILED and stay out until a newer successful read-only validation exists. This does NOT change the
scanner or the latch rules. It only does what the 08:40 token refresh already does: when the latch is blocked, it runs validate_market_data_authorization.py (ONE read-only
LTP quote; the file is written only when the quote returns a positive price). A bad token or an outage leaves the latch untouched.

    python aplus_post_open_latch_check.py        exit 0 always; one line appended to data/logs/post_open_latch_check.log
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
STATE = ROOT / "data" / "intraday_movement"
LOG = ROOT / "data" / "logs" / "post_open_latch_check.log"
MAX_PER_DAY = 8


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as h:
        h.write(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} {msg}\n")


def _attempts_today() -> int:
    try:
        day = f"{datetime.now(IST):%Y-%m-%d}"
        return sum(1 for line in LOG.read_text(encoding="utf-8").splitlines() if line.startswith(day) and "running validator" in line)
    except OSError:
        return 0


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from scanner_authorization_state import scanner_authorization_is_blocked
    from trading_calendar import is_trading_day

    now = datetime.now(IST)
    if not is_trading_day(now.date())[0]:
        return 0
    if not scanner_authorization_is_blocked(STATE / "scanner_runtime_health.json", STATE / "market_data_authorization_validation.json"):
        return 0                                           # latch is clear: nothing to do, nothing logged
    if _attempts_today() >= MAX_PER_DAY:
        _log("latch blocked; daily attempt cap reached - needs a manual look")
        return 0
    _log("latch blocked; running validator (one read-only quote)")
    try:
        out = subprocess.run([sys.executable, str(ROOT / "validate_market_data_authorization.py")], capture_output=True, text=True, timeout=60, cwd=str(ROOT))
        _log(f"validator exit {out.returncode}: {(out.stdout or out.stderr).strip()[:200]}")
    except Exception as exc:                               # noqa: BLE001
        _log(f"validator failed to run: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
