"""NSE trading-day check for the scanner.

A day is a trading day unless it is a weekend or listed in
data/safety/nse_holidays.csv. This module FAILS OPEN: if the holiday file is
missing or unreadable the day is treated as a trading day, so a data problem
can never stop a real session.

Set APLUS_FORCE_TRADING_DAY=1 to override (for example a special Saturday
session such as Muhurat trading).
"""

from __future__ import annotations

import csv
import os
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HOLIDAY_FILE = PROJECT_ROOT / "data" / "safety" / "nse_holidays.csv"

_cache: dict[str, tuple[float, dict[date, str]]] = {}


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def load_holidays(path: Path | str = DEFAULT_HOLIDAY_FILE) -> dict[date, str]:
    """Return {date: description}; empty dict if the file is missing/unreadable."""
    file = Path(path)
    try:
        mtime = file.stat().st_mtime
    except OSError:
        return {}
    cached = _cache.get(str(file))
    if cached and cached[0] == mtime:
        return cached[1]
    holidays: dict[date, str] = {}
    try:
        with file.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                day = _parse_date(row.get("date"))
                if day is not None:
                    holidays[day] = str(row.get("description") or "").strip()
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    _cache[str(file)] = (mtime, holidays)
    return holidays


def is_trading_day(
    day: date,
    holiday_file: Path | str = DEFAULT_HOLIDAY_FILE,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """Return (is_trading_day, reason)."""
    environ = os.environ if env is None else env
    if str(environ.get("APLUS_FORCE_TRADING_DAY", "")).strip() in ("1", "true", "TRUE", "yes"):
        return True, "FORCED_BY_APLUS_FORCE_TRADING_DAY"
    if day.weekday() >= 5:
        return False, "WEEKEND"
    holidays = load_holidays(holiday_file)
    if day in holidays:
        return False, f"NSE_HOLIDAY: {holidays[day] or 'listed in nse_holidays.csv'}"
    return True, "TRADING_DAY"
