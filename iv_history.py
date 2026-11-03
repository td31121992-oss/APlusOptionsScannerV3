"""Per-stock ATM implied-volatility history, for an 'IV rank' shadow tag (research only; never affects a trade).

record() keeps the FIRST ATM IV seen for a stock each day in data/iv_history/<SYMBOL>.csv (day,iv). rank() says where an IV sits among the last
`window` recorded days, 0 (cheapest the stock has been) .. 100 (dearest); blank until at least MIN_DAYS days exist, so it fills up over time.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_DAYS = 10
_seen: set[tuple[str, str]] = set()


def _path(symbol: str, root: Path) -> Path:
    return root / "data" / "iv_history" / f"{symbol}.csv"


def load(symbol: str, root: Path = ROOT) -> list[tuple[str, float]]:
    try:
        with _path(symbol, root).open(encoding="utf-8", newline="") as h:
            return [(r["day"], float(r["iv"])) for r in csv.DictReader(h) if r.get("iv")]
    except (OSError, ValueError, KeyError):
        return []


def record(symbol: str, iv: float, day: str | None = None, root: Path = ROOT) -> None:
    day = day or date.today().isoformat()
    if iv <= 0 or (symbol, day) in _seen:
        return
    _seen.add((symbol, day))
    try:
        if any(d == day for d, _ in load(symbol, root)):
            return
        p = _path(symbol, root)
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with p.open("a", encoding="utf-8", newline="") as h:
            if new:
                h.write("day,iv\n")
            h.write(f"{day},{iv:.2f}\n")
    except OSError:
        pass


def rank(symbol: str, iv: float, window: int = 60, root: Path = ROOT, day: str | None = None) -> float | None:
    day = day or date.today().isoformat()
    past = [v for d, v in load(symbol, root) if d < day][-window:]
    if len(past) < MIN_DAYS or iv <= 0:
        return None
    return round(100.0 * sum(1 for v in past if v <= iv) / len(past), 0)
