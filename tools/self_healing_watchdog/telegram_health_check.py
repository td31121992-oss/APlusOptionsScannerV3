"""09:10 pre-market Telegram health message for APlus (and a CAlphaTrader status line).

Replaces the earlier version, which reported 'APlus NOT RUNNING' at 09:10 even
though the scanner is (by design) started at 09:14:44. This version checks
READINESS: token life, supervisor, safety data, and that the morning-start task
is armed. It sends through CAlphaTrader's existing Telegram sender.

    python telegram_health_check.py            # check and send
    python telegram_health_check.py --dry-run  # check and print only (nothing sent)

Exit code: 0 ok, 2 Telegram send failed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CALPHA = Path.home() / "Desktop" / "CAlphaTrader"
LOG = ROOT / "data" / "self_healing" / "telegram_health_check.log"
sys.path.insert(0, str(ROOT))


def log(msg: str) -> None:
    line = f"{datetime.now().astimezone().isoformat()} | {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    print(line)


def _ps(command: str, timeout: int = 20) -> str:
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                             capture_output=True, text=True, timeout=timeout)
        return (out.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"ERROR {type(exc).__name__}"


def task_ready(name: str) -> bool | None:
    out = _ps(f"(Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue).State")
    if not out or out.startswith("ERROR"):
        return None
    return out in ("Ready", "Running")


def calpha_running() -> bool:
    out = _ps("Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*CAlphaTrader*' -and "
              "($_.CommandLine -like '*main.py*' -or $_.CommandLine -like '*start_trading_day*')} | "
              "Select-Object -First 1 -ExpandProperty ProcessId")
    return bool(out) and not out.startswith("ERROR")


def live_token_ok() -> bool:
    """Confirm the shared Dhan token against Dhan /profile (retrying transient failures)."""
    try:
        from dotenv import load_dotenv
        import os
        from dhan_auth import resolve_access_token

        load_dotenv(ROOT / ".env")
        client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
        return bool(resolve_access_token(project_root=ROOT, client_id=client_id,
                                         env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip()))
    except Exception:  # noqa: BLE001
        return False


def build_message(now: datetime, token_ok: bool, items: dict[str, dict], tasks: dict[str, bool | None],
                  calpha: bool, market_note: str) -> tuple[str, str]:
    """Return (status, text). Pure function (unit-tested)."""
    def mark(level: str) -> str:
        return {"ok": "✅", "warn": "⚠️", "bad": "❌"}.get(level, "➖")

    bad = (not token_ok) or any(items.get(k, {}).get("level") == "bad" for k in ("Supervisor", "Market-data authorization"))
    bad = bad or tasks.get("APlusOptionsScannerV3_MorningStart") is not True
    warn = any(v.get("level") == "warn" for v in items.values())
    status = "NOT READY" if bad else ("CHECK" if warn else "READY")
    icon = {"READY": "🟢", "CHECK": "🟡", "NOT READY": "🔴"}[status]

    tok = items.get("Dhan token", {})
    sup = items.get("Supervisor", {})
    mwpl = items.get("MWPL / ban data", {})
    ev = items.get("Corporate events", {})
    lines = [
        f"{icon} 09:10 APlus pre-market check - {now:%a %d %b}",
        "",
        f"Dhan token: {mark('ok' if token_ok else 'bad')} {tok.get('value', 'unknown')}" + ("" if token_ok else " (live check FAILED)"),
        f"Supervisor: {mark(sup.get('level', ''))} {sup.get('value', 'unknown')}",
        f"Scanner: {mark('ok' if tasks.get('APlusOptionsScannerV3_MorningStart') else 'bad')} auto-starts 09:14",
        f"Safety data: {mark(mwpl.get('level', ''))} MWPL {mwpl.get('value', 'n/a')} ({mwpl.get('detail', '')}); "
        f"{mark(ev.get('level', ''))} {ev.get('value', 'n/a')}",
        f"CAlphaTrader: {'✅ running' if calpha else '⏳ not started yet (starts ~09:13)'}",
        f"Market: {market_note}",
        "Mode: PAPER ONLY",
        "",
        {"READY": "System is ready for the open.", "CHECK": "Ready, with warnings - see above.",
         "NOT READY": "NOT READY - attention required before 09:14."}[status],
    ]
    return status, "\n".join(lines)


def send(message: str) -> tuple[bool, str]:
    py = CALPHA / ".venv" / "Scripts" / "python.exe"
    tools_dir = CALPHA / "tools"
    if not py.exists() or not (tools_dir / "telegram_alerts.py").exists():
        return False, "CAlpha Telegram sender missing"
    code = f"import sys; sys.path.insert(0, r'{tools_dir}'); import telegram_alerts as t; t.send_message(sys.argv[1])"
    try:
        p = subprocess.run([str(py), "-c", code, message], cwd=str(CALPHA), capture_output=True, text=True, timeout=90)
        return p.returncode == 0, ((p.stdout or "") + (p.stderr or ""))[-600:]
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def main() -> int:
    import dashboard_intel as di

    dry = "--dry-run" in sys.argv
    now = datetime.now(di.IST)
    market = di.market_status(now, ROOT)
    health = di.health(ROOT, now, market)
    items = {i["key"]: i for i in health["items"]}
    tasks = {n: task_ready(n) for n in ("APlusOptionsScannerV3_MorningStart", "APlus_Master_Self_Healing")}
    status, text = build_message(now, live_token_ok(), items, tasks, calpha_running(), f"{market['state']} ({market['note']})")
    if dry:
        print(text)
        log(f"DRY RUN status={status} (nothing sent)")
        return 0
    ok, detail = send(text)
    log(f"HEALTH status={status} telegram_ok={ok}")
    if detail:
        log("TELEGRAM_DETAIL " + detail.replace("\r", " ").replace("\n", " | "))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
