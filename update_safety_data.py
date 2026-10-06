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
COMBINE_OI_URL = "https://nsearchives.nseindia.com/archives/nsccl/mwpl/combineoi_{stamp}.zip"
EVENT_URL = "https://www.nseindia.com/api/event-calendar"
SOURCE_EVENTS = "NSE event-calendar"
SOURCE_OI = "NSE combineoi"
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


def parse_combine_oi(text: str) -> tuple[date, list[dict]]:
    """Parse NSE combineoi CSV into (data_date, rows).

    MWPL utilization % = future-equivalent open interest / MWPL * 100.
    """
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    data_date: date | None = None
    for raw in reader:
        rec = {str(k).strip(): (v or "").strip() for k, v in raw.items() if k}
        symbol = rec.get("NSE Symbol", "").upper()
        if not symbol:
            continue
        try:
            mwpl = float(rec["MWPL"])
            fut_eq = float(rec["Future Equivalent Open Interest"])
            day = datetime.strptime(rec["Date"].title(), "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        if mwpl <= 0:
            continue
        data_date = data_date or day
        rows.append({
            "symbol": symbol,
            "utilization": round(fut_eq / mwpl * 100.0, 2),
            "no_fresh": rec.get("Limit for Next Day", "").lower().startswith("no fresh"),
        })
    if data_date is None or not rows:
        raise ValueError("combineoi file had no usable rows")
    return data_date, rows


def fetch_combine_oi(session: requests.Session, today: date | None = None) -> tuple[date, list[dict]]:
    """Fetch the most recent combineoi file (tries today back through 6 days)."""
    import zipfile
    from datetime import timedelta

    today = today or date.today()
    last_error: Exception | None = None
    for back in range(0, 7):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        url = COMBINE_OI_URL.format(stamp=day.strftime("%d%m%Y"))
        try:
            response = session.get(url, timeout=25)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
                return parse_combine_oi(archive.read(name).decode("utf-8", "ignore"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"no combineoi file found ({last_error})")


def update_ban_list(session: requests.Session) -> bool:
    """Write mwpl_status.csv: MWPL utilization for every stock plus today's ban list."""
    ban_date: date | None = None
    ban_symbols: list[str] = []
    try:
        response = session.get(BAN_URL, timeout=25)
        response.raise_for_status()
        ban_date, ban_symbols = parse_ban_list(response.text)
    except Exception as exc:  # noqa: BLE001
        print(f"BAN LIST FETCH FAILED: {type(exc).__name__}: {exc}")

    oi_date: date | None = None
    oi_rows: list[dict] = []
    try:
        oi_date, oi_rows = fetch_combine_oi(session)
    except Exception as exc:  # noqa: BLE001
        print(f"MWPL UTILIZATION FETCH FAILED: {type(exc).__name__}: {exc}")

    if ban_date is None and not oi_rows:
        print("MWPL/BAN NOT UPDATED: both sources failed; keeping existing file")
        return False

    out: dict[str, list[str]] = {}
    for rec in oi_rows:
        status = "FNO_BAN" if rec["no_fresh"] else ""
        out[rec["symbol"]] = [
            rec["symbol"], oi_date.isoformat(), f"{rec['utilization']:.2f}", status,
            SOURCE_OI, "Future-equivalent OI / MWPL",
        ]
    if ban_date is not None:  # official ban list for the trade date overrides
        for sym in ban_symbols:
            prior = out.get(sym)
            util = prior[2] if prior else ""
            out[sym] = [sym, ban_date.isoformat(), util, "FNO_BAN", SOURCE_BAN, "In F&O ban period per NSE"]

    rows = [out[k] for k in sorted(out)]
    _atomic_write_csv(
        SAFETY_DIR / "mwpl_status.csv",
        ["symbol", "as_of", "mwpl_utilization_percent", "status", "source", "notes"],
        rows,
    )
    high = sum(1 for r in rows if r[2] and float(r[2]) >= 80.0)
    print(
        f"MWPL UPDATED: rows={len(rows)} oi_date={oi_date.isoformat() if oi_date else None} "
        f"ban_date={ban_date.isoformat() if ban_date else None} in_ban={len(ban_symbols)} "
        f"at_or_above_80pct={high}"
    )
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


HIGH_PURPOSE = ("RESULT",)  # earnings announcements: block new entries inside the gate window


def parse_events(payload, as_of: date) -> list[list[str]]:
    """Convert NSE event-calendar rows into corporate_events.csv rows."""
    rows = payload if isinstance(payload, list) else (payload or {}).get("data", [])
    out: list[list[str]] = []
    for item in rows or []:
        symbol = str(item.get("symbol") or "").strip().upper()
        raw_date = str(item.get("date") or "").strip()
        if not symbol or not raw_date:
            continue
        try:
            event_day = datetime.strptime(raw_date.title(), "%d-%b-%Y").date()
        except ValueError:
            continue
        purpose = str(item.get("purpose") or "UNKNOWN").strip().upper()
        severity = "HIGH" if any(tag in purpose for tag in HIGH_PURPOSE) else "MEDIUM"
        notes = " ".join(str(item.get("bm_desc") or "").split())[:140]
        out.append([symbol, event_day.isoformat(), purpose, severity, as_of.isoformat(), SOURCE_EVENTS, notes])
    return sorted(out, key=lambda r: (r[1], r[0]))


def update_events(session: requests.Session) -> bool:
    try:
        session.get(HOME_URL, timeout=20)
        response = session.get(
            EVENT_URL,
            headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar"},
            timeout=30,
        )
        response.raise_for_status()
        rows = parse_events(response.json(), date.today())
    except Exception as exc:  # noqa: BLE001
        print(f"EVENTS NOT UPDATED: {type(exc).__name__}: {exc}")
        return False
    if len(rows) < 10:
        print(f"EVENTS NOT UPDATED: only {len(rows)} rows returned; keeping existing file")
        return False
    _atomic_write_csv(
        SAFETY_DIR / "corporate_events.csv",
        ["symbol", "event_date", "event_type", "severity", "as_of", "source", "notes"],
        rows,
    )
    high = sum(1 for r in rows if r[3] == "HIGH")
    print(f"EVENTS UPDATED: {len(rows)} events ({high} HIGH/results) {rows[0][1]} .. {rows[-1][1]}")
    return True


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "*/*"})
    ok_ban = update_ban_list(session)
    ok_hol = update_holidays(session)
    ok_evt = update_events(session)
    return 0 if (ok_ban and ok_hol and ok_evt) else 1


if __name__ == "__main__":
    sys.exit(main())
