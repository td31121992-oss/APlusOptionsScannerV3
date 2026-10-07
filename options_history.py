"""Read the downloaded historical option candles (see download_expired_options.py) for backtests.

    from options_history import load_series, coverage
    df = load_series("RELIANCE", "CALL", offset=0, start="2025-09-01", end="2025-12-31")
    #   index: timestamp (IST); columns: open high low close volume oi iv strike spot

Series are 'rolling': at every timestamp the contract is the near-month (exp_code=1) option
whose strike is `offset` steps from the money at that time (offset 0 = ATM, +1 = next strike
up, -1 = next strike down). The `strike` column tells you which actual strike that was.
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

DEFAULT_ROOT = Path(os.getenv("APLUS_OPTIONS_HISTORY", r"E:\APlusData\expired_options"))
IST = timezone(timedelta(hours=5, minutes=30))
COLUMNS = ["open", "high", "low", "close", "volume", "oi", "iv", "strike", "spot"]


def _label(offset: int) -> str:
    return "ATM" if offset == 0 else f"ATM{offset:+d}"


def _read(path: Path, side: str) -> pd.DataFrame:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        blk = (((json.load(handle).get("response") or {}).get("data") or {}).get("ce" if side == "CALL" else "pe")) or {}
    if not blk.get("timestamp"):
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.DataFrame({c: blk.get(c) for c in COLUMNS}, index=pd.to_datetime(blk["timestamp"], unit="s", utc=True).tz_convert(IST))
    frame.index.name = "timestamp"
    return frame


def load_series(symbol: str, side: str, offset: int = 0, exp_code: int = 1, start: str | date | None = None,
                end: str | date | None = None, root: Path | str = DEFAULT_ROOT) -> pd.DataFrame:
    """Concatenate every stored 30-day window for one rolling series (empty frame if none)."""
    side = side.upper()
    if side not in ("CALL", "PUT"):
        raise ValueError("side must be CALL or PUT")
    tag = f"{exp_code}_{'CE' if side == 'CALL' else 'PE'}_{_label(offset)}.json.gz"
    base = Path(root) / symbol.upper()
    frames = []
    if base.is_dir():
        for window in sorted(p for p in base.iterdir() if p.is_dir()):
            f = window / tag
            if f.exists():
                frames.append(_read(f, side))
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    if start is not None:
        out = out[out.index >= pd.Timestamp(start, tz=IST)]
    if end is not None:
        out = out[out.index < pd.Timestamp(end, tz=IST) + pd.Timedelta(days=1)]
    return out


def coverage(root: Path | str = DEFAULT_ROOT) -> pd.DataFrame:
    """Per symbol: windows stored, windows with data, candles in the ATM call series, date range."""
    rows = []
    base = Path(root)
    for sym_dir in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        stored = with_data = 0
        first = last = None
        for window in sorted(p for p in sym_dir.iterdir() if p.is_dir()):
            f = window / "1_CE_ATM.json.gz"
            if not f.exists():
                continue
            stored += 1
            n = len(_read(f, "CALL"))
            if n:
                with_data += 1
                first = first or window.name
                last = window.name
        rows.append({"symbol": sym_dir.name, "windows_stored": stored, "windows_with_data": with_data, "first_window": first, "last_window": last})
    return pd.DataFrame(rows)
