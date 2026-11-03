"""Stop alert: a Telegram message whenever something that should be running is not. Run once a minute by the APlus_Stop_Alert scheduled task. READ-ONLY on the trading software.

    python stop_alert.py              check everything, send alerts, keep state
    python stop_alert.py --dry-run    print the status table only (nothing sent, no state written)
    python stop_alert.py --test       send one "watcher armed" message (checks the Telegram channel)

For every item in COMPONENTS: inside its time window (trading days only, unless it is 24x7) it must be healthy. Down for GRACE_SECONDS in a row -> one STOPPED message; still down ->
a reminder every REMIND_SECONDS; healthy again -> one BACK message. A message that fails to send is retried on the next run. Items outside their window are never reported.
Sends through CAlphaTrader's existing Telegram sender (the same one the 09:10 health message uses). Written after the news collector died on 27 Oct and nobody was told.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
CALPHA = Path.home() / "Desktop" / "CAlphaTrader"
OUT = ROOT / "data" / "alerts"
STATE = OUT / "stop_alert_state.json"
HEALTH = OUT / "stop_alert_health.json"
LOG = OUT / "stop_alert.log"
HOLIDAYS = ROOT / "data" / "safety" / "nse_holidays.csv"
IST = timezone(timedelta(hours=5, minutes=30))

GRACE_SECONDS = 120          # two checks in a row (the task runs every minute)
REMIND_SECONDS = 1800
MIN_FREE_GB = 3.0


@dataclass(frozen=True)
class Component:
    name: str
    check: Callable[["Context"], tuple[bool, str]]
    window: tuple[dtime, dtime] | None = None      # None = 24x7 (every day); otherwise trading days only, inside this IST window


class Context:
    """One snapshot of the machine: running processes and the clock."""

    def __init__(self, procs: list[str], now: datetime) -> None:
        self.procs, self.now = procs, now

    def running(self, pattern: str) -> int:
        rx = re.compile(pattern, re.I)
        return sum(1 for c in self.procs if rx.search(c))


# checks -------------------------------------------------------------------------------------------------------------------------------------------------------------------
def proc(pattern: str, label: str = "") -> Callable[[Context], tuple[bool, str]]:
    def check(ctx: Context) -> tuple[bool, str]:
        n = ctx.running(pattern)
        return (n > 0, "running" if n else f"process not found{(' (' + label + ')') if label else ''}")
    return check


def fresh_file(path: Path, max_age_s: float) -> Callable[[Context], tuple[bool, str]]:
    def check(ctx: Context) -> tuple[bool, str]:
        try:
            age = ctx.now.timestamp() - path.stat().st_mtime
        except OSError:
            return False, f"{path.name} missing"
        return (age <= max_age_s, f"{path.name} updated {int(age)}s ago" + ("" if age <= max_age_s else f" (limit {int(max_age_s)}s)"))
    return check


def tick_recorder(ctx: Context) -> tuple[bool, str]:
    if not ctx.running(r"\\tick_recorder\.py"):
        return False, "process not found"
    ok, detail = fresh_file(ROOT / "data" / "ticks" / "health.json", 150)(ctx)
    if not ok:
        return False, detail
    try:
        quiet = (json.loads((ROOT / "data" / "ticks" / "health.json").read_text(encoding="utf-8")) or {}).get("seconds_since_packet")
    except (OSError, ValueError):
        return True, detail
    if isinstance(quiet, (int, float)) and quiet > 240:
        return False, f"no market tick for {int(quiet)}s"
    return True, "receiving ticks"


def port_open(port: int) -> Callable[[Context], tuple[bool, str]]:
    def check(ctx: Context) -> tuple[bool, str]:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True, f"port {port} answering"
        except OSError:
            return False, f"port {port} not answering"
    return check


def disk_space(ctx: Context) -> tuple[bool, str]:
    free = shutil.disk_usage(ROOT.anchor or "C:\\").free / 1024 ** 3
    return (free >= MIN_FREE_GB, f"C: has {free:.1f} GB free" + ("" if free >= MIN_FREE_GB else f" (alert below {MIN_FREE_GB:.0f} GB - recorders and logs start failing)"))


T = dtime
COMPONENTS: tuple[Component, ...] = (
    Component("APlus scanner", fresh_file(ROOT / "data" / "intraday_movement" / "scanner_runtime_health.json", 300), (T(9, 20), T(15, 30))),
    Component("APlus dashboard", port_open(8765), (T(9, 0), T(16, 0))),
    Component("Stock tick recorder", tick_recorder, (T(9, 16), T(15, 30))),
    Component("Option tick recorder", proc(r"\\option_tick_recorder\.py"), (T(9, 16), T(15, 30))),
    Component("Futures recorder", proc(r"\\futures_recorder\.py"), (T(9, 16), T(15, 30))),
    Component("Upstox chain collector", proc(r"\\upstox_chain_collector\.py"), (T(9, 16), T(15, 30))),
    Component("News collector", proc(r"\\aplus_overnight_intelligence\.py")),
    Component("Announcement service", proc(r"\\aplus_announcement_service\.py")),
    Component("Order book recorder", proc(r"\\order_book_recorder\.py")),
    Component("Chirag shadow", proc(r"\\chirag_shadow\.py")),
    Component("Master self-healing supervisor", proc(r"aplus_master_self_healing_supervisor\.ps1")),
    Component("CAlphaTrader supervisor", proc(r"-m ops\.supervisor")),
    Component("CAlphaTrader quote hub", proc(r"CAlphaTrader.*run_quote_hub\.py"), (T(9, 16), T(15, 30))),
    Component("CAlphaTrader scanner", proc(r"CAlphaTrader.*main\.py --loop"), (T(9, 16), T(15, 30))),
    Component("Gate outcome tracker (16:20 task)", fresh_file(Path(r"E:\APlusData\top_movers_study\gate_outcome_check.txt"), 3 * 3600), (T(17, 0), T(19, 0))),
    Component("Disk space", disk_space),
)


# logic --------------------------------------------------------------------------------------------------------------------------------------------------------------------
def is_trading_day(now: datetime, holidays: set[str]) -> bool:
    return now.weekday() < 5 and now.strftime("%Y-%m-%d") not in holidays


def in_window(comp: Component, now: datetime, holidays: set[str]) -> bool:
    if comp.window is None:
        return True
    return is_trading_day(now, holidays) and comp.window[0] <= now.time() <= comp.window[1]


def step(entry: dict[str, Any], ok: bool, active: bool, now_ts: float, detail: str) -> tuple[dict[str, Any], str | None]:
    """Advance one component's state. Returns (new_state, 'stopped' | 'remind' | 'back' | None)."""
    e = dict(entry or {})
    if not active:                                      # outside its window: forget it, never report it
        return {}, None
    if ok:
        was_alerted, since = bool(e.get("alerted_at")), e.get("down_since")
        e = {"last_ok": now_ts}
        if was_alerted:
            e["back_after"] = round(now_ts - float(now_ts if since is None else since))
            return e, "back"
        return e, None
    e.setdefault("down_since", now_ts)
    e["detail"] = detail
    if not e.get("alerted_at"):
        if now_ts - e["down_since"] >= GRACE_SECONDS:
            return e, "stopped"
        return e, None
    if now_ts - float(e.get("reminded_at", e["alerted_at"])) >= REMIND_SECONDS:
        return e, "remind"
    return e, None


def message(kind: str, name: str, e: dict[str, Any], now: datetime) -> str:
    since = datetime.fromtimestamp(float(e.get("down_since", now.timestamp())), IST)
    mins = max(1, int((now.timestamp() - since.timestamp()) // 60))
    if kind == "back":
        return f"\U0001F7E2 APlus BACK: {name}\nIt was down about {max(1, int(e.get('back_after', 0)) // 60)} min and is healthy again ({now:%H:%M} IST)."
    head = "\U0001F534 APlus STOPPED" if kind == "stopped" else "\U0001F534 APlus STILL DOWN"
    return f"{head}: {name}\nDown since {since:%H:%M} IST ({mins} min).\n{e.get('detail', '')}"


# machine access -----------------------------------------------------------------------------------------------------------------------------------------------------------
def list_processes() -> list[str]:
    cmd = "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine } | ForEach-Object { $_.CommandLine }"
    out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [ln for ln in (out.stdout or "").splitlines() if ln.strip()]


def holidays() -> set[str]:
    try:
        lines = HOLIDAYS.read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        return set()                                    # fails open: a missing file means every weekday is a trading day
    return {ln.split(",")[0].strip() for ln in lines if ln.strip()}


def send(text: str) -> tuple[bool, str]:
    py, tools = CALPHA / ".venv" / "Scripts" / "python.exe", CALPHA / "tools"
    if not py.exists() or not (tools / "telegram_alerts.py").exists():
        return False, "CAlpha Telegram sender missing"
    code = f"import sys; sys.path.insert(0, r'{tools}'); import telegram_alerts as t; t.send_message(sys.argv[1])"
    try:
        p = subprocess.run([str(py), "-c", code, text], cwd=str(CALPHA), capture_output=True, text=True, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode == 0, ((p.stdout or "") + (p.stderr or ""))[-300:]
    except Exception as exc:                            # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def log(line: str) -> None:
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(IST).isoformat(timespec='seconds')} {line}\n")
    except OSError:
        pass


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run(dry: bool = False) -> int:
    now = datetime.now(IST)
    hol = holidays()
    ctx = Context(list_processes(), now)
    state, new_state, rows = load_state(), {}, []
    for comp in COMPONENTS:
        active = in_window(comp, now, hol)
        try:
            ok, detail = comp.check(ctx) if active else (True, "outside its window")
        except Exception as exc:                        # noqa: BLE001 - a broken check must not hide the others
            ok, detail = False, f"check failed: {type(exc).__name__}: {exc}"
        entry, action = step(state.get(comp.name, {}), ok, active, now.timestamp(), detail)
        rows.append((comp.name, active, ok, detail, action))
        if action and not dry:
            sent, why = send(message(action, comp.name, entry, now))
            log(f"{action.upper()} {comp.name}: {detail} | telegram {'sent' if sent else 'FAILED ' + why}")
            if sent:
                if action == "stopped":
                    entry["alerted_at"] = entry["reminded_at"] = now.timestamp()
                elif action == "remind":
                    entry["reminded_at"] = now.timestamp()
                elif action == "back":
                    entry = {"last_ok": now.timestamp()}
            elif action == "back":
                entry = {**state.get(comp.name, {}), "last_ok": now.timestamp()}          # keep the alerted state so the BACK message is retried
        new_state[comp.name] = entry
    if dry:
        for name, active, ok, detail, action in rows:
            print(f"{'OK  ' if ok else 'DOWN'} {'     ' if active else 'idle '} {name:28s} {detail}{'   -> would send ' + action if action else ''}")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(new_state, indent=1), encoding="utf-8")
    HEALTH.write_text(json.dumps({"updated_at": now.isoformat(timespec="seconds"), "monitored": len(COMPONENTS), "down": [r[0] for r in rows if r[1] and not r[2]]}, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str]) -> int:
    if "--test" in argv:
        ok, why = send(f"\u2705 APlus stop-alert watcher is armed: {len(COMPONENTS)} items checked every minute. You will get a message here when any of them stops.")
        print("sent" if ok else f"FAILED: {why}")
        return 0 if ok else 2
    return run(dry="--dry-run" in argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
