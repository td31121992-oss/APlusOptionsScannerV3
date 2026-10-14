"""Manual controls for open PAPER trades: set a stop-loss yourself, or exit a trade now.

The dashboard only appends a command to data/manual_orders/<date>.jsonl (it never edits the journal, which the scanner owns).
The scanner's paper journal reads that file every position update and applies it:

  STOP   - sets `manual_stop` on the trade. A manual stop can only TIGHTEN risk (it is used when it is above the trade's current
           protective stop); it can never widen a stop, so the Rs 3,500 per-trade loss cap and the ladder still hold.
           Exit reason when it fires: MANUAL_STOP_LOSS.
  CLEAR  - removes the manual stop.
  EXIT   - closes the trade at the next valid option mark. Exit reason: MANUAL_EXIT.

Commands are idempotent: the journal derives the latest wish per trade from the whole day's file each time.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
KINDS = ("STOP", "CLEAR", "EXIT")


def _dir(root: Path | str) -> Path:
    return Path(root) / "data" / "manual_orders"


def _path(root: Path | str, day: str) -> Path:
    return _dir(root) / f"{day}.jsonl"


def add(root: Path | str, trade_id: str, kind: str, value: float | None = None, source: str = "dashboard",
        when: datetime | None = None) -> dict[str, Any]:
    kind = str(kind).upper()
    if kind not in KINDS:
        raise ValueError(f"unknown manual command {kind!r}")
    if not str(trade_id).strip():
        raise ValueError("trade id is required")
    if kind == "STOP" and not (value and float(value) > 0):
        raise ValueError("a manual stop needs a price above zero")
    when = when or datetime.now()
    entry = {"id": uuid.uuid4().hex[:12], "ts": when.isoformat(timespec="seconds"), "trade_id": str(trade_id), "kind": kind,
             "value": round(float(value), 2) if value else None, "source": source}
    path = _path(root, when.date().isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def read(root: Path | str, day: str) -> list[dict[str, Any]]:
    path = _path(root, day)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("kind") in KINDS and item.get("trade_id"):
            out.append(item)
    return out


def desired_state(commands: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Latest wish per trade id: {"stop": float|None, "stop_at": ts, "exit_at": ts|None}."""
    state: dict[str, dict[str, Any]] = {}
    for c in commands:
        s = state.setdefault(str(c["trade_id"]), {"stop": None, "stop_at": None, "exit_at": None})
        if c["kind"] == "STOP":
            s["stop"], s["stop_at"] = float(c.get("value") or 0) or None, c.get("ts")
        elif c["kind"] == "CLEAR":
            s["stop"], s["stop_at"] = None, c.get("ts")
        elif c["kind"] == "EXIT" and not s["exit_at"]:
            s["exit_at"] = c.get("ts")
    return state


def current_stop(trade: Mapping[str, Any]) -> float:
    """The protective stop the trade has right now (original stop, or the ladder stop once it is higher)."""
    def num(key: str) -> float:
        try:
            v = float(trade.get(key) or 0)
            return v if v == v else 0.0
        except (TypeError, ValueError):
            return 0.0
    return max(num("option_stop"), num("ladder_stop"), num("runner_stop"))


def validate_stop(trade: Mapping[str, Any], stop: float) -> tuple[bool, str]:
    if str(trade.get("status") or "").upper() != "OPEN":
        return False, "This trade is not open."
    try:
        last = float(trade.get("last_option_price") or 0)
    except (TypeError, ValueError):
        last = 0.0
    if stop <= 0:
        return False, "Enter a stop price above zero."
    cur = current_stop(trade)
    if stop <= cur:
        return False, f"Stop must be above the current stop ({cur:.2f}); a manual stop can only tighten risk."
    if last > 0 and stop >= last:
        return False, f"Stop must be below the last price ({last:.2f}). Use Exit now to leave at the market."
    return True, "ok"


def enabled() -> bool:
    return os.getenv("APLUS_MANUAL_CONTROLS", "ON").strip().upper() != "OFF"


def heartbeat(root: Path | str, when: datetime | None = None) -> None:
    """Called by the journal on every position update, so the dashboard can tell whether the RUNNING scanner understands manual
    commands (a scanner started before this feature existed never writes it)."""
    try:
        path = _dir(root) / "heartbeat.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ts": (when or datetime.now()).isoformat(timespec="seconds")}), encoding="utf-8")
    except OSError:
        pass


def scanner_ready(root: Path | str, max_age_seconds: int = 240, now: datetime | None = None) -> bool:
    try:
        ts = json.loads((_dir(root) / "heartbeat.json").read_text(encoding="utf-8"))["ts"]
        age = ((now or datetime.now()) - datetime.fromisoformat(ts).replace(tzinfo=None)).total_seconds()
        return -5 <= age <= max_age_seconds
    except (OSError, ValueError, KeyError, TypeError):
        return False
