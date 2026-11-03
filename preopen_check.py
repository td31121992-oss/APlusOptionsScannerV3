"""One-screen readiness / health check for APlus. Read-only; sends nothing.

Run any time (before 09:14 for pre-open, or during the session):
    .venv\\Scripts\\python.exe preopen_check.py

Also writes data/logs/preopen_check_<date>.txt. Exit code 0 = no problems, 1 = at least one FAIL.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import dashboard_intel as di

ROOT = Path(__file__).resolve().parent
TASKS = [
    "APlus_Safety_Data_Refresh", "APlusOptionsScannerV3_MorningStart", "APlus_Master_Self_Healing",
    "APlus_MidSession_Token_Refresh", "APlusOptionsScannerV3_Postmarket_Analysis",
]


def _task_info(name: str) -> str:
    cmd = (f"$t=Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; if(-not $t){{'MISSING'}}else{{"
           f"$i=$t|Get-ScheduledTaskInfo; '{{0}}|{{1}}|{{2}}' -f $t.State,$i.LastTaskResult,$i.NextRunTime}}")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "UNKNOWN"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR {type(exc).__name__}"


def main() -> int:
    now = datetime.now(di.IST)
    market = di.market_status(now, ROOT)
    lines: list[str] = []
    problems = 0

    def row(level: str, key: str, text: str) -> None:
        nonlocal problems
        if level == "FAIL":
            problems += 1
        lines.append(f"[{level:4s}] {key:28s} {text}")

    lines.append(f"APlus check  {now:%a %d %b %Y %H:%M} IST   market: {market['state']} ({market['note']})")
    lines.append("-" * 78)

    for item in di.health(ROOT, now, market)["items"]:
        level = {"ok": "OK", "warn": "WARN", "bad": "FAIL"}.get(item["level"], "INFO")
        row(level, item["key"], f"{item['value']}  {item['detail']}".strip())

    funnel = di.funnel(ROOT, now, market)
    row("INFO", "Diagnosis", funnel["diagnosis"])

    for name in TASKS:
        info = _task_info(name)
        if info == "MISSING":
            row("FAIL", f"task {name[:23]}", "task is missing")
            continue
        try:
            state, last, nxt = info.split("|")
            level = "OK" if state in ("Ready", "Running") else "WARN"
            row(level, f"task {name[:23]}", f"{state}, last result {last}, next {nxt}")
        except ValueError:
            row("WARN", f"task {name[:23]}", info)

    free_gb = shutil.disk_usage(ROOT).free / 1e9
    row("OK" if free_gb > 10 else "WARN", "Disk free", f"{free_gb:.0f} GB")

    with socket.socket() as s:
        s.settimeout(1)
        up = s.connect_ex(("127.0.0.1", 8765)) == 0
    row("OK" if up else ("WARN" if market["state"] != "OPEN" else "FAIL"), "Dashboard :8765", "listening" if up else "not running")

    try:
        pos = di.positions(ROOT, now)
        if pos["stale_session"]:
            row("INFO", "Leftover open trades", pos["note"])
    except Exception:  # noqa: BLE001
        pass

    text = "\n".join(lines) + "\n" + "-" * 78 + f"\n{'ALL CLEAR' if not problems else str(problems) + ' PROBLEM(S) - see FAIL lines'}\n"
    print(text)
    try:
        out = ROOT / "data" / "logs" / f"preopen_check_{now:%Y%m%d_%H%M}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
