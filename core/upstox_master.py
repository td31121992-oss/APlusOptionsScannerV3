"""Instrument master built from Upstox's own file, in the column layout of Dhan's "detailed" scrip master.

The Dhan plan expired on 3 Nov 2026. NSE security ids are the NSE exchange tokens, and Upstox publishes the same token as `exchange_token`, so every id the system
already uses (stock, option, future) stays exactly the same; only the file it is read from changes. The result is written to the same
data/cache/api-scrip-master-detailed.csv, so core/instrument_loader.py, futures_flow.py, the futures paper engine and the report scripts read it unchanged.

Rows written (NSE only): stock equity (SERIES EQ), stock options, stock futures, index options and index futures. Columns the readers do not use stay blank.
Tick size: Upstox and Dhan both give it in paise (5.0 = Rs 0.05); the loader divides by 100.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
COLUMNS = ["EXCH_ID", "SEGMENT", "SECURITY_ID", "ISIN", "INSTRUMENT", "UNDERLYING_SECURITY_ID", "UNDERLYING_SYMBOL", "SYMBOL_NAME", "DISPLAY_NAME",
           "INSTRUMENT_TYPE", "SERIES", "LOT_SIZE", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE", "TICK_SIZE", "EXPIRY_FLAG", "ASM_GSM_FLAG",
           "ASM_GSM_CATEGORY", "SM_UPPER_LIMIT", "SM_LOWER_LIMIT", "SM_FREEZE_QTY"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _expiry(ms: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=IST)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _strike_text(strike: float) -> str:
    return f"{strike:g}"


def _display_strike(strike: float) -> str:
    """Dhan style: whole strikes without decimals (720), fractional ones with two (172.50)."""
    return f"{int(strike)}" if float(strike).is_integer() else f"{strike:.2f}"


def rows_from_upstox(master: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Dhan-shaped rows for the NSE equity, stock / index options and futures in the Upstox master."""
    master = list(master)
    equity: dict[str, Mapping[str, Any]] = {}                      # Upstox instrument_key -> the stock's NSE_EQ row
    for r in master:
        if r.get("segment") == "NSE_EQ" and r.get("instrument_type") == "EQ" and r.get("exchange_token") and r.get("instrument_key"):
            equity[str(r["instrument_key"])] = r
    out: list[dict[str, Any]] = []
    for r in equity.values():
        out.append({"EXCH_ID": "NSE", "SEGMENT": "E", "SECURITY_ID": str(r["exchange_token"]), "ISIN": r.get("isin") or "", "INSTRUMENT": "EQUITY",
                    "UNDERLYING_SECURITY_ID": "", "UNDERLYING_SYMBOL": str(r.get("trading_symbol") or "").upper(),
                    "SYMBOL_NAME": str(r.get("name") or r.get("trading_symbol") or "").upper(), "DISPLAY_NAME": r.get("short_name") or r.get("name") or "",
                    "INSTRUMENT_TYPE": "ES", "SERIES": "EQ", "LOT_SIZE": 1.0, "SM_EXPIRY_DATE": "", "STRIKE_PRICE": "", "OPTION_TYPE": "",
                    "TICK_SIZE": _num(r.get("tick_size"), 5.0), "SM_FREEZE_QTY": r.get("freeze_quantity") or ""})
    for r in master:
        if r.get("segment") != "NSE_FO" or not r.get("exchange_token"):
            continue
        kind = str(r.get("instrument_type") or "")
        if kind not in {"CE", "PE", "FUT"}:
            continue
        exp = _expiry(r.get("expiry"))
        if exp is None:
            continue
        sym = str(r.get("underlying_symbol") or r.get("asset_symbol") or "").upper()
        if not sym:
            continue
        stock = str(r.get("underlying_type") or "").upper() in {"EQUITY", ""} and str(r.get("underlying_key") or "") in equity
        under = equity.get(str(r.get("underlying_key") or ""))
        lot = _num(r.get("lot_size"), 0.0)
        month = f"{_MONTHS[exp.month - 1]}{exp.year}"
        base = {"EXCH_ID": "NSE", "SEGMENT": "D", "SECURITY_ID": str(r["exchange_token"]), "ISIN": "", "UNDERLYING_SECURITY_ID": str(under["exchange_token"]) if under else "",
                "UNDERLYING_SYMBOL": sym, "SERIES": "", "LOT_SIZE": lot, "SM_EXPIRY_DATE": exp.date().isoformat(), "TICK_SIZE": _num(r.get("tick_size"), 5.0),
                "SM_FREEZE_QTY": r.get("freeze_quantity") or ""}
        if kind == "FUT":
            out.append({**base, "INSTRUMENT": "FUTSTK" if stock else "FUTIDX", "SYMBOL_NAME": f"{sym}-{month}-FUT",
                        "DISPLAY_NAME": f"{sym} {_MONTHS[exp.month - 1].upper()} FUT", "INSTRUMENT_TYPE": "FUT", "STRIKE_PRICE": -0.01, "OPTION_TYPE": "XX"})
        else:
            strike = _num(r.get("strike_price"), 0.0)
            out.append({**base, "INSTRUMENT": "OPTSTK" if stock else "OPTIDX", "SYMBOL_NAME": f"{sym}-{month}-{_strike_text(strike)}-{kind}",
                        "DISPLAY_NAME": f"{sym} {exp.day:02d} {_MONTHS[exp.month - 1].upper()} {_display_strike(strike)} {'CALL' if kind == 'CE' else 'PUT'}",
                        "INSTRUMENT_TYPE": "OP", "STRIKE_PRICE": strike, "OPTION_TYPE": kind})
    return out


def write_master_csv(master: Iterable[Mapping[str, Any]], path: Path) -> int:
    """Write the Dhan-shaped CSV atomically; returns the number of rows. Refuses to overwrite a good file with a thin one."""
    rows = rows_from_upstox(master)
    stocks = sum(1 for r in rows if r["INSTRUMENT"] == "OPTSTK")
    equity = sum(1 for r in rows if r["INSTRUMENT"] == "EQUITY")
    if stocks < 10000 or equity < 1000:
        raise RuntimeError(f"Upstox instrument master looks incomplete: {stocks} stock options, {equity} equities")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
    logger.info("Instrument master built from Upstox: %s (%d rows, %d stock options)", path, len(rows), stocks)
    return len(rows)
