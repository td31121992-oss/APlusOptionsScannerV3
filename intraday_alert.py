"""Mid-session alert (read-only; no AI; no trading effect): tells you on Telegram when the scanner stops doing its job during market hours.

The self-healing supervisor restarts a dead scanner but never says so, and a scanner that is alive but stuck is not restarted at all. Run every 5 minutes (a Windows task), this checks:

    CYCLES_STALLED      no scanner cycle for 6 minutes during the session (and the session is more than 6 minutes old)
    CYCLES_FAILING      3 or more failed cycles in the last 10 minutes
    POSITIONS_UNMANAGED an open paper position whose price was last updated more than 3 minutes ago (stops and targets are not being watched)
    AUTH                the scanner's authorisation health is not HEALTHY
    DISK                less than 2 GB free

Each problem is sent once when it starts, again after 30 minutes if it is still there, and a "recovered" line when it clears. Nothing is sent outside market hours or on a non-trading day.

    python intraday_alert.py [--dry-run]       --dry-run prints what it would send and writes nothing
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "intraday_alert_state.json"
SESSION_START, SESSION_END = (9, 20), (15, 35)
STALL_MINUTES, FAIL_WINDOW_MINUTES, FAIL_LIMIT, UNMANAGED_MINUTES, REPEAT_MINUTES, MIN_DISK_GB = 6, 10, 3, 3, 30, 2.0


def in_session(now: datetime) -> bool:
    hm = (now.hour, now.minute)
    if not (SESSION_START <= hm <= SESSION_END):
        return False
    try:
        from trading_calendar import is_trading_day

        return bool(is_trading_day(now.date())[0])
    except Exception:                                      # noqa: BLE001 - without the calendar fall back to weekdays
        return now.weekday() < 5


def log_tail(root: Path, max_bytes: int = 400_000) -> list[str]:
    path = root / "logs" / "scanner.log"
    try:
        with path.open("rb") as h:
            h.seek(0, 2)
            size = h.tell()
            h.seek(max(0, size - max_bytes))
            return h.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def stamp(line: str) -> datetime | None:
    try:
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def evaluate(now: datetime, root: Path = ROOT) -> dict[str, str]:
    """Current problems: name -> one-line description. Empty outside the session or when everything is fine."""
    if not in_session(now):
        return {}
    problems: dict[str, str] = {}
    lines = log_tail(root)
    today = now.date().isoformat()
    cycles = [s for l in lines if l.startswith(today) and "Intraday movement cycle phase" in l and (s := stamp(l))]
    session_age = (now - now.replace(hour=SESSION_START[0], minute=SESSION_START[1], second=0, microsecond=0)).total_seconds() / 60
    if cycles:
        quiet = (now - max(cycles)).total_seconds() / 60
        if quiet >= STALL_MINUTES:
            problems["CYCLES_STALLED"] = f"no scanner cycle for {quiet:.0f} minutes (last at {max(cycles):%H:%M})"
    elif session_age >= STALL_MINUTES + 5:
        problems["CYCLES_STALLED"] = "no scanner cycle has run today"
    cutoff = now - timedelta(minutes=FAIL_WINDOW_MINUTES)
    failed = [s for l in lines if l.startswith(today) and "cycle failed" in l.lower() and (s := stamp(l)) and s >= cutoff]
    if len(failed) >= FAIL_LIMIT:
        problems["CYCLES_FAILING"] = f"{len(failed)} failed scanner cycles in the last {FAIL_WINDOW_MINUTES} minutes"
    try:
        trades = json.loads((root / "data" / "intraday_movement" / "paper_trade_journal.json").read_text(encoding="utf-8")).get("trades", [])
    except (OSError, ValueError):
        trades = []
    stale = []
    for t in trades:
        if str(t.get("status")).upper() != "OPEN":
            continue
        q = t.get("last_quote_time") or t.get("entry_time")
        try:
            age = (now - datetime.fromisoformat(str(q)).replace(tzinfo=None)).total_seconds() / 60
        except ValueError:
            continue
        if age >= UNMANAGED_MINUTES:
            stale.append(f"{t.get('symbol')} ({age:.0f} min)")
    if stale:
        problems["POSITIONS_UNMANAGED"] = "open positions whose price is not being updated: " + ", ".join(stale[:5])
    try:
        status = json.loads((root / "data" / "intraday_movement" / "scanner_runtime_health.json").read_text(encoding="utf-8")).get("status")
        if status not in (None, "HEALTHY"):
            problems["AUTH"] = f"scanner health is {status}"
    except (OSError, ValueError):
        pass
    try:
        free = shutil.disk_usage(root).free / 1e9
        if free < MIN_DISK_GB:
            problems["DISK"] = f"only {free:.1f} GB of disk left"
    except OSError:
        pass
    return problems


def decide(previous: Mapping[str, Any], problems: Mapping[str, str], now: datetime) -> tuple[list[str], dict[str, Any]]:
    """(messages to send, new state). A problem is sent when it starts and again every REPEAT_MINUTES while it lasts; a cleared one sends a 'recovered' line."""
    messages: list[str] = []
    state: dict[str, Any] = {}
    for name, text in problems.items():
        last = previous.get(name)
        try:
            due = last is None or (now - datetime.fromisoformat(last)).total_seconds() / 60 >= REPEAT_MINUTES
        except ValueError:
            due = True
        if due:
            messages.append(f"APlus {now:%H:%M} ALERT {name}: {text}")
        state[name] = now.isoformat(timespec="seconds") if due else last
    for name in previous:
        if name not in problems:
            messages.append(f"APlus {now:%H:%M} recovered: {name}")
    return messages, state


def main() -> int:
    dry = "--dry-run" in sys.argv
    now = datetime.now()
    try:
        previous = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    problems = evaluate(now)
    if not in_session(now):
        problems = {}
    messages, state = decide(previous, problems, now)
    for m in messages:
        print(m)
    if not messages:
        print(f"{now:%H:%M} all fine" if in_session(now) else f"{now:%H:%M} outside the session; nothing to check")
    if dry:
        return 0
    if messages:
        sys.path.insert(0, str(ROOT))
        import pipeline_watchdog

        ok, detail = pipeline_watchdog.send_telegram("\n".join(messages))
        print("telegram:", "sent" if ok else f"NOT sent ({detail[:100]})")
        if not ok:
            return 1                                       # keep the old state so the next run tries again
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
