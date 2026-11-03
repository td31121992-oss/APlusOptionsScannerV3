"""Pause / resume NEW paper entries from the dashboard (the scanner keeps running and keeps managing open trades).

State lives in data/control/entries_pause.json, written by the dashboard and read by the scanner before every new entry:

    {"paused": true, "reason": "manual", "since": "...", "by": "dashboard:127.0.0.1",
     "target_pct": 7.0,            # optional: pause automatically once the day's P&L reaches this % of account capital
     "target_day": "2026-10-15"}   # the day the target was set for; a target never carries over to the next day

A manual pause is cleared at the next session day (it applies to the day it was set), so tomorrow starts normally.
Open trades are never touched: stops, exits, ladder, watch alerts and manual Manage orders all keep working.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent


def _path(root: Path | str) -> Path:
    return Path(root) / "data" / "control" / "entries_pause.json"


def _today(today: date | None = None) -> str:
    return (today or date.today()).isoformat()


def account_capital() -> float:
    """Same figure the safety gate uses (APLUS_SAFETY_ACCOUNT_CAPITAL, default Rs 5,00,000)."""
    try:
        return max(1.0, float(os.getenv("APLUS_SAFETY_ACCOUNT_CAPITAL", "500000")))
    except ValueError:
        return 500000.0


def heartbeat(root: Path | str, now: datetime | None = None) -> None:
    """Written by the scanner every cycle: proves the running scanner knows about this switch."""
    try:
        _write_file(Path(root) / "data" / "control" / "entries_pause_heartbeat.json", {"ts": (now or datetime.now()).isoformat()})
    except OSError:
        pass


def scanner_ready(root: Path | str, max_age_seconds: int = 300, now: datetime | None = None) -> bool:
    try:
        ts = json.loads((Path(root) / "data" / "control" / "entries_pause_heartbeat.json").read_text(encoding="utf-8"))["ts"]
        age = ((now or datetime.now()) - datetime.fromisoformat(ts).replace(tzinfo=None)).total_seconds()
        return -5 <= age <= max_age_seconds
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _write_file(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(state), handle)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read(root: Path | str = ROOT) -> dict[str, Any]:
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(root: Path | str, state: Mapping[str, Any]) -> None:
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(state), handle)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def set_state(root: Path | str, paused: bool | None = None, target_pct: float | None = None, clear_target: bool = False,
              by: str = "dashboard", now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    state = read(root)
    day = now.date().isoformat()
    if paused is not None:
        state.update({"paused": bool(paused), "since": now.isoformat(timespec="seconds"), "by": by,
                      "reason": "manual" if paused else "", "day": day})
    if clear_target:
        state.pop("target_pct", None)
        state.pop("target_day", None)
    elif target_pct is not None:
        value = float(target_pct)
        if not (0 < value <= 100):
            raise ValueError("target must be between 0 and 100 percent")
        state["target_pct"], state["target_day"] = round(value, 2), day
    _write(root, state)
    return state


def check(root: Path | str, day_pnl: float | None = None, capital: float | None = None, today: date | None = None) -> tuple[bool, str]:
    """(entries_blocked, reason). Fail-open: any problem reading the file means entries are NOT blocked."""
    try:
        state = read(root)
        day = _today(today)
        if state.get("paused") and state.get("day") == day:
            return True, "PAUSED_BY_USER"
        target = state.get("target_pct")
        if target and state.get("target_day") == day and day_pnl is not None and capital and capital > 0:
            if day_pnl / capital * 100.0 >= float(target):
                return True, f"DAY_TARGET_REACHED_{float(target):g}PCT"
        return False, ""
    except Exception:                                      # noqa: BLE001 - never stop the scanner because of a control file
        return False, ""


def day_pnl(trades: Iterable[Mapping[str, Any]], day: str) -> float:
    """Realized + unrealized P&L of the paper trades entered on `day` (same fields the dashboard uses)."""
    total = 0.0
    for t in trades:
        if str(t.get("entry_time") or t.get("generated_at") or "")[:10] != day:
            continue
        for key in ("total_pnl", "net_pnl", "realized_pnl"):
            try:
                value = t.get(key)
                if value not in (None, ""):
                    total += float(value)
                    break
            except (TypeError, ValueError):
                continue
    return round(total, 2)


def status(root: Path | str, pnl: float | None, capital: float, today: date | None = None) -> dict[str, Any]:
    state = read(root)
    day = _today(today)
    blocked, reason = check(root, pnl, capital, today)
    return {"paused": bool(state.get("paused") and state.get("day") == day), "blocked": blocked, "reason": reason,
            "since": state.get("since", ""), "by": state.get("by", ""),
            "target_pct": state.get("target_pct") if state.get("target_day") == day else None,
            "day_pnl": pnl, "capital": capital, "scanner_ready": scanner_ready(root),
            "day_pct": round(pnl / capital * 100.0, 2) if (pnl is not None and capital) else None}
