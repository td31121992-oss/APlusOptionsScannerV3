"""Adds the time and %-from-open of each stock's day high / day low to the F&O market-watch rows. Read-only.

The scanner's market-watch rows carry day_high / day_low prices but not when they happened. The order-book recorder stores
every stock's last price about once a minute (data/order_book/<date>.csv); this module reads that file incrementally and
remembers the minute at which each stock's recorded price was highest / lowest. Times are therefore accurate to about a
minute; when the recorded extreme differs from the exchange day high/low by more than 0.2% (a spike between two readings)
the time is marked approximate ("~").
"""

from __future__ import annotations

import csv
import threading
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"file": None, "offset": 0, "header": None, "ext": {}}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _refresh(path: Path) -> None:
    st = _STATE
    try:
        size = path.stat().st_size
    except OSError:
        return
    if st["file"] != str(path) or size < st["offset"]:
        st.update(file=str(path), offset=0, header=None, ext={})
    if size == st["offset"]:
        return
    try:
        with path.open("rb") as handle:
            handle.seek(st["offset"])
            chunk = handle.read()
    except OSError:
        return
    end = chunk.rfind(b"\n")
    if end < 0:
        return                                           # no complete line yet
    st["offset"] += end + 1
    lines = chunk[: end + 1].decode("utf-8", errors="replace").splitlines()
    if st["header"] is None:
        if not lines:
            return
        st["header"] = next(csv.reader([lines.pop(0)]))
    for row in csv.reader(lines):
        if len(row) != len(st["header"]):
            continue
        r = dict(zip(st["header"], row))
        sym, ltp, t = r.get("symbol", ""), _f(r.get("ltp")), r.get("time", "")[11:16]
        if not sym or ltp <= 0 or not t:
            continue
        e = st["ext"].setdefault(sym, {"hi": ltp, "hi_t": t, "lo": ltp, "lo_t": t})
        if ltp > e["hi"]:
            e["hi"], e["hi_t"] = ltp, t
        if ltp < e["lo"]:
            e["lo"], e["lo_t"] = ltp, t


def enrich(payload: dict[str, Any], root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    rows = payload.get("rows") or []
    path = root / "data" / "order_book" / f"{(today or date.today()).isoformat()}.csv"
    with _LOCK:
        try:
            _refresh(path)
        except Exception:                                # noqa: BLE001 - the page must still load without times
            pass
        ext = dict(_STATE["ext"]) if _STATE["file"] == str(path) else {}
    for r in rows:
        o, hi, lo = _f(r.get("open_0915")), _f(r.get("day_high")), _f(r.get("day_low"))
        r["high_from_open_pct"] = round((hi / o - 1) * 100, 2) if o > 0 and hi > 0 else None
        r["low_from_open_pct"] = round((lo / o - 1) * 100, 2) if o > 0 and lo > 0 else None
        e = ext.get(str(r.get("symbol")))
        if not e:
            r["high_time"] = r["low_time"] = ""
            continue
        at_open_hi, at_open_lo = o > 0 and abs(hi - o) / o < 0.0002, o > 0 and abs(lo - o) / o < 0.0002
        r["high_time"] = "09:15" if at_open_hi else ("~" if hi > 0 and abs(e["hi"] - hi) / hi > 0.002 else "") + e["hi_t"]
        r["low_time"] = "09:15" if at_open_lo else ("~" if lo > 0 and abs(e["lo"] - lo) / lo > 0.002 else "") + e["lo_t"]
    return payload
