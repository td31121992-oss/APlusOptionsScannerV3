from __future__ import annotations

import datetime as dt
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
REPORTS = DATA / "reports"
LOGS = DATA / "logs"
OUT_DIR = REPORTS / "incident_diagnostics"

PROCESS_PATTERNS = (
    "main.py",
    "intraday-movement",
    "paper_safety_evidence_agent",
    "two_scanner_self_healing_watchdog",
    "aplus_live_pnl_dashboard",
    "stock_futures_paper_engine",
    "rollover_paper_state",
)

WATCH_FILES = (
    DATA / "reports" / "fno_market_watch_latest.json",
    DATA / "reports" / "fno_market_watch_latest.csv",
    DATA / "reports" / "paper_trades_latest.json",
    DATA / "reports" / "paper_safety_evidence_status.json",
    DATA / "portfolio_state.json",
    DATA / "logs" / "paper_safety_evidence_agent.log",
    DATA / "logs" / "paper_safety_evidence_agent_launcher.log",
    DATA / "self_healing_watchdog" / "watchdog.log",
)

TASK_NAMES = (
    "APlus_CAlpha_Self_Healing_Watchdog_V6",
    "APlus_CAlpha_Tomorrow_Recovery",
    "APlus_Paper_Safety_Evidence_Agent",
    "APlus_Final_Reliability_Watchdog",
)


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def run_powershell(script: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-30000:],
            "stderr": completed.stderr[-10000:],
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def collect_processes() -> dict[str, Any]:
    script = r"""
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -in @('python.exe','pythonw.exe','cmd.exe','powershell.exe') -and $_.CommandLine -and $_.CommandLine -match 'APlusOptionsScannerV3' } |
  Select-Object ProcessId,ParentProcessId,Name,CreationDate,ExecutablePath,CommandLine |
  ConvertTo-Json -Depth 4
"""
    result = run_powershell(script)
    raw = result.get("stdout", "").strip()
    try:
        result["records"] = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        result["records"] = []
        result["parse_warning"] = "PowerShell process output was not valid JSON"
    return result


def collect_tasks() -> dict[str, Any]:
    names = ",".join(json.dumps(name) for name in TASK_NAMES)
    script = f"""
$names = @({names})
$result = foreach ($name in $names) {{
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if ($task) {{
    $info = Get-ScheduledTaskInfo -TaskName $name -ErrorAction SilentlyContinue
    [pscustomobject]@{{
      TaskName=$name; State=[string]$task.State; Actions=@($task.Actions | ForEach-Object {{ [pscustomobject]@{{Execute=$_.Execute;Arguments=$_.Arguments;WorkingDirectory=$_.WorkingDirectory}} }}); LastRunTime=$info.LastRunTime; LastTaskResult=$info.LastTaskResult; NextRunTime=$info.NextRunTime
    }}
  }}
}}
$result | ConvertTo-Json -Depth 8
"""
    result = run_powershell(script)
    raw = result.get("stdout", "").strip()
    try:
        result["records"] = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        result["records"] = []
        result["parse_warning"] = "PowerShell task output was not valid JSON"
    return result


def file_snapshot(path: Path) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return item
    try:
        stat = path.stat()
        item.update(
            size=stat.st_size,
            modified=dt.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
            read_only=not os.access(path, os.W_OK),
        )
        if path.suffix.lower() == ".json" and stat.st_size <= 2_000_000:
            try:
                json.loads(path.read_text(encoding="utf-8-sig"))
                item["json_valid"] = True
            except Exception as exc:
                item["json_valid"] = False
                item["json_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        item["error"] = f"{type(exc).__name__}: {exc}"
    return item


def latest_files() -> list[dict[str, Any]]:
    candidates: list[Path] = []
    for folder in (REPORTS, DATA / "opening_momentum", DATA / "opportunity_tracker"):
        if folder.exists():
            candidates.extend(path for path in folder.rglob("*") if path.is_file())
    rows = []
    for path in candidates:
        try:
            stat = path.stat()
            rows.append({"path": str(path), "modified": dt.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"), "size": stat.st_size})
        except OSError:
            continue
    return sorted(rows, key=lambda row: row["modified"], reverse=True)[:30]


def classify(snapshot: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    records = snapshot.get("processes", {}).get("records", [])
    text = json.dumps(records).lower()
    if "intraday-movement" not in text:
        findings.append("APlus intraday-movement process was not found in the process inventory.")
    if "two_scanner_self_healing_watchdog" in text:
        findings.append("Self-healing watchdog process is present.")
    if "aplus_live_pnl_dashboard" in text:
        findings.append("Live P&L dashboard process is present.")
    state = next((row for row in snapshot["files"] if row["path"].endswith("portfolio_state.json")), None)
    if state and state.get("exists") and state.get("json_valid") is False:
        findings.append("portfolio_state.json exists but is not valid JSON.")
    market = next((row for row in snapshot["files"] if row["path"].endswith("fno_market_watch_latest.json")), None)
    if not market or not market.get("exists"):
        findings.append("F&O market-watch JSON is missing.")
    return findings


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, Any] = {
        "generated_at": now(),
        "root": str(ROOT),
        "python": sys.version,
        "platform": platform.platform(),
        "processes": collect_processes(),
        "scheduled_tasks": collect_tasks(),
        "files": [file_snapshot(path) for path in WATCH_FILES],
        "latest_activity": latest_files(),
    }
    snapshot["findings"] = classify(snapshot)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output = OUT_DIR / f"incident_{stamp}.json"
    output.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    latest = OUT_DIR / "latest.json"
    latest.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": "OK", "report": str(output), "latest": str(latest), "findings": snapshot["findings"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
