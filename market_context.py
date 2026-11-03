"""Market-trend context (NIFTY / BANKNIFTY / India VIX) for the paper scanner.

The index quotes ride on the scanner's existing marketfeed/quote request (no
extra API call). Every cycle the context is appended to
data/market_context/<date>.csv so it can later be joined to trades.

APLUS_MARKET_REGIME_MODE:
  OFF     - do nothing (no extra instruments requested)
  SHADOW  - (default) record context only; never blocks a trade
  ENFORCE - also drop counter-trend candidates: BULLISH in a BEAR regime and
            BEARISH in a BULL regime (CHOP allows both)

Regime uses NIFTY's move from the previous close (P) and from today's open (O):
BULL if P >= +T and O >= 0; BEAR if P <= -T and O <= 0; otherwise CHOP
(T = APLUS_REGIME_THRESHOLD_PCT, default 0.30).
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, MutableMapping

INDEX_SEGMENT = "IDX_I"
INDEX_IDS = {"NIFTY": 13, "BANKNIFTY": 25, "INDIAVIX": 21}
FIELDS = [
    "time", "regime", "nifty_ltp", "nifty_pct_prev", "nifty_pct_open",
    "banknifty_ltp", "banknifty_pct_prev", "banknifty_pct_open", "vix", "vix_pct_prev",
]


def mode() -> str:
    value = os.getenv("APLUS_MARKET_REGIME_MODE", "SHADOW").strip().upper()
    return value if value in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def threshold_pct() -> float:
    try:
        return max(0.0, float(os.getenv("APLUS_REGIME_THRESHOLD_PCT", "0.30")))
    except ValueError:
        return 0.30


def add_to_request(quote_request: MutableMapping[str, list]) -> None:
    """Add the index instruments to an existing quote request (no-op when OFF)."""
    if mode() != "OFF":
        quote_request[INDEX_SEGMENT] = list(INDEX_IDS.values())


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # reject NaN


def _pct(now: float | None, base: float | None) -> float | None:
    if now is None or base is None or base <= 0:
        return None
    return round((now - base) / base * 100.0, 3)


def _index_row(segment: Mapping[str, Any], security_id: int) -> tuple[float | None, float | None, float | None]:
    item = segment.get(str(security_id)) or {}
    ohlc = item.get("ohlc") or {}
    ltp = _num(item.get("last_price"))
    return ltp, _num(ohlc.get("close")), _num(ohlc.get("open"))


def classify(nifty_pct_prev: float | None, nifty_pct_open: float | None, threshold: float | None = None) -> str:
    t = threshold_pct() if threshold is None else threshold
    if nifty_pct_prev is None:
        return "UNKNOWN"
    open_move = 0.0 if nifty_pct_open is None else nifty_pct_open
    if nifty_pct_prev >= t and open_move >= 0:
        return "BULL"
    if nifty_pct_prev <= -t and open_move <= 0:
        return "BEAR"
    return "CHOP"


def summarize(quote_map: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build the context dict from a normalised {segment: {id: payload}} quote map."""
    segment = (quote_map or {}).get(INDEX_SEGMENT)
    if not isinstance(segment, Mapping) or not segment:
        return None
    n_ltp, n_prev, n_open = _index_row(segment, INDEX_IDS["NIFTY"])
    b_ltp, b_prev, b_open = _index_row(segment, INDEX_IDS["BANKNIFTY"])
    v_ltp, v_prev, _ = _index_row(segment, INDEX_IDS["INDIAVIX"])
    nifty_prev, nifty_open = _pct(n_ltp, n_prev), _pct(n_ltp, n_open)
    return {
        "regime": classify(nifty_prev, nifty_open),
        "nifty_ltp": n_ltp, "nifty_pct_prev": nifty_prev, "nifty_pct_open": nifty_open,
        "banknifty_ltp": b_ltp, "banknifty_pct_prev": _pct(b_ltp, b_prev), "banknifty_pct_open": _pct(b_ltp, b_open),
        "vix": v_ltp, "vix_pct_prev": _pct(v_ltp, v_prev),
    }


def direction_allowed(regime: str, direction: str, current_mode: str | None = None) -> bool:
    """True unless ENFORCE mode and the trade is against the market regime."""
    if (current_mode or mode()) != "ENFORCE":
        return True
    d = str(direction).upper()
    if regime == "BEAR" and d == "BULLISH":
        return False
    if regime == "BULL" and d == "BEARISH":
        return False
    return True


def record(context: Mapping[str, Any], when: datetime, base_dir: Path | str) -> None:
    """Append one row to data/market_context/<date>.csv (never raises)."""
    try:
        folder = Path(base_dir) / "market_context"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{when.date().isoformat()}.csv"
        new_file = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            writer.writerow({"time": when.isoformat(timespec="seconds"), **context})
    except Exception:  # noqa: BLE001 - context logging must never affect trading
        pass
