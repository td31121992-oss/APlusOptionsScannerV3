"""When did each Decision Desk candidate first become entry-ready, and since when has each gate said what it says now?

Replays today's per-cycle scanner reports (data/reports/intraday_movement_<date>_<time>.json) once, in time order, through the
same row logic the Decision Desk uses (decision_desk.build_rows), and remembers per stock/direction:
  first_ready   the first cycle in which the candidate was entry-ready or already gated
  aplus_since   the cycle in which the A+ gate verdict last changed to what it is now (e.g. 09:41 PASS, or 09:44 REJECT)
  v2_since      the same for the V2 gate
  traded_at     the cycle in which the paper trade appeared
Files are parsed once and only new ones afterwards, so the Decision Desk page stays fast. Read-only.
"""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"day": None, "done": set(), "times": {}}


def _hm(report: dict[str, Any], name: str) -> str:
    stamp = str(report.get("generated_at") or "")
    if len(stamp) >= 16:
        return stamp[11:16]
    tail = name.rsplit("_", 1)[-1].split(".")[0]
    return f"{tail[:2]}:{tail[2:4]}" if len(tail) >= 4 else ""


def _apply(report: dict[str, Any], hm: str, times: dict[tuple[str, str], dict[str, str]]) -> None:
    import decision_desk

    for r in decision_desk.build_rows(report, "UNKNOWN"):
        key = (str(r["symbol"]), str(r["direction"]))
        t = times.setdefault(key, {"first_ready": hm, "aplus": "", "aplus_since": hm, "v2": "", "v2_since": hm, "traded_at": ""})
        if r["gate_aplus"] != t["aplus"]:
            t["aplus"], t["aplus_since"] = r["gate_aplus"], hm
        if r["gate_v2"] != t["v2"]:
            t["v2"], t["v2_since"] = r["gate_v2"], hm
        if r["status"] == "TRADED" and not t["traded_at"]:
            t["traded_at"] = hm


def load(root: Path = ROOT, today: date | None = None) -> dict[tuple[str, str], dict[str, str]]:
    day = (today or date.today()).strftime("%Y%m%d")
    files = sorted((root / "data" / "reports").glob(f"intraday_movement_{day}_*.json"))
    with _LOCK:
        if _STATE["day"] != (day, str(root)):
            _STATE.update(day=(day, str(root)), done=set(), times={})
        for f in files:
            if f.name in _STATE["done"]:
                continue
            try:
                report = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue                                   # half-written file: retry next time
            _STATE["done"].add(f.name)
            try:
                _apply(report, _hm(report, f.name), _STATE["times"])
            except Exception:                              # noqa: BLE001 - times are a nicety, never break the page
                continue
        return {k: dict(v) for k, v in _STATE["times"].items()}


def attach(rows: list[dict[str, Any]], root: Path = ROOT) -> None:
    try:
        times = load(root)
    except Exception:                                      # noqa: BLE001
        return
    for r in rows:
        t = times.get((str(r.get("symbol")), str(r.get("direction"))))
        if not t:
            continue
        r.update(first_ready=t["first_ready"], aplus_since=t["aplus_since"], v2_since=t["v2_since"], traded_at=t["traded_at"])
