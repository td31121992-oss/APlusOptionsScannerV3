"""Refresh the safety-gate reference data from official NSE sources.

Writes (atomically, with a timestamped backup of the previous file):
  data/safety/nse_holidays.csv   <- NSE holiday master, equity-derivatives (FO) segment
  data/safety/mwpl_status.csv    <- NSE F&O ban list (symbols currently in ban)

A failed or empty fetch NEVER overwrites existing data. Read-only against NSE;
no orders, no credentials. Exit code 0 on success, 1 if any dataset failed.

Usage:  python update_safety_data.py
"""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
SAFETY_DIR = PROJECT_ROOT / "data" / "safety"
BACKUP_DIR = PROJECT_ROOT / "_archive" / "safety_backups"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
BAN_URL = "https://nsearchives.nseindia.com/content/fo/fo_secban.csv"
HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
HOME_URL = "https://www.nseindia.com/"
SOURCE_BAN = "NSE fo_secban.csv"
SOURCE_HOLIDAY = "NSE holiday-master (FO)"


def _backup(path: Path) -> None:
    if path.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, BACKUP_DIR / f"{path.stem}_{stamp}{path.suffix}")


def _atomic_write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    os.replace(tmp, path)


def parse_ban_list(text: str) -> tuple[date, list[str]]:
    """Return (trade_date, symbols) from NSE's fo_secban.csv content."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty ban-list response")
    match = re.search(r"Trade Date\s+(\d{2}-[A-Za-z]{3}-\d{4})", lines[0])
    if not match:
        raise ValueError("ban-list header has no trade date")
    trade_date = datetime.strptime(match.group(1).title(), "%d-%b-%Y").date()
    symbols = []
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) >= 2 and parts[1]:
            symbols.append(parts[1].upper())
    return trade_date, symbols


def parse_holidays(payload: dict) -> list[tuple[date, str]]:
    rows = payload.get("FO") or []
    out = []
    for item in rows:
        day = datetime.strptime(str(item["tradingDate"]).title(), "%d-%b-%Y").date()
        out.append((day, str(item.get("description") or "").strip()))
    return sorted(out)


def update_ban_list(session: requests.Session) -> bool:
    try:
        response = session.get(BAN_URL, timeout=25)
        response.raise_for_status()
        trade_date, symbols = parse_ban_list(response.text)
    except Exception as exc:  # noqa: BLE001
        print(f"BAN LIST NOT UPDATED: {type(exc).__name__}: {exc}")
        return False
    rows = [
        [sym, trade_date.isoformat(), "", "FNO_BAN", SOURCE_BAN, "In F&O ban period per NSE"]
        for sym in symbols
    ]
    _atomic_write_csv(
        SAFETY_DIR / "mwpl_status.csv",
        ["symbol", "as_of", "mwpl_utilization_percent", "status", "source", "notes"],
        rows,
    )
    print(f"BAN LIST UPDATED: trade_date={trade_date.isoformat()} symbols_in_ban={len(symbols)} {symbols}")
    return True


def update_holidays(session: requests.Session) -> bool:
    try:
        session.get(HOME_URL, timeout=20)  # obtain NSE session cookies
        response = session.get(
            HOLIDAY_URL,
            headers={"Referer": "https://www.nseindia.com/resources/exchange-communication-holidays"},
            timeout=25,
        )
        response.raise_for_status()
        holidays = parse_holidays(response.json())
    except Exception as exc:  # noqa: BLE001
        print(f"HOLIDAYS NOT UPDATED: {type(exc).__name__}: {exc}")
        return False
    if len(holidays) < 10:
        print(f"HOLIDAYS NOT UPDATED: only {len(holidays)} rows returned; keeping existing file")
        return False
    _atomic_write_csv(
        SAFETY_DIR / "nse_holidays.csv",
        ["date", "description"],
        [[d.isoformat(), desc] for d, desc in holidays],
    )
    print(f"HOLIDAYS UPDATED: {len(holidays)} dates {holidays[0][0]} .. {holidays[-1][0]}")
    return True


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "*/*"})
    ok_ban = update_ban_list(session)
    ok_hol = update_holidays(session)
    return 0 if (ok_ban and ok_hol) else 1


if __name__ == "__main__":
    sys.exit(main())
