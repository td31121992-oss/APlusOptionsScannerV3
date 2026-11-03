"""Futures recorder (DATA ONLY - never touches the scanner or any trade).

Once a minute in market hours it saves, from Upstox (free analytics token, read-only), the near-month and next-month future of every F&O stock and of NIFTY, BANKNIFTY,
FINNIFTY and MIDCPNIFTY, together with the cash / index price, so that open interest, volume and basis (the future's premium over the cash price) can be studied later.

    data/futures/<day>.csv.gz       one row per contract per minute (columns below), appended as a new gzip member
    data/futures/health.json        cycles, contracts ok, last error

    kind        STK / IDX for a future, VIX for the India VIX reading (spot only)
    contract    NEAR or NEXT (the nearest expiry that is at least MIN_DAYS away is NEAR; indices use the nearest expiry)
    basis_pct   future / spot - 1, in %      oi, volume   as reported for the contract today      prev_close  the contract's previous close

    python futures_recorder.py              run until 15:30 on trading days
    python futures_recorder.py --once [--symbols TCS,INFY] [--out DIR]   one pass (for a test), writes to --out (default a temp folder)

Settings: APLUS_FUTURES_SECONDS (60), APLUS_FUTURES_MIN_DAYS (2: a stock future closer than this to expiry is skipped, like the scanner's tags).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
START, END = (9, 13), (15, 30)
INDEX_FUTURES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
VIX_KEY = "NSE_INDEX|India VIX"
FIELDS = ["captured_at", "symbol", "kind", "contract", "expiry", "dte", "lot", "fut_ltp", "spot", "basis_pct", "oi", "volume", "avg_price", "buy_qty", "sell_qty",
          "prev_close", "open", "high", "low", "bid", "bid_qty", "ask", "ask_qty"]


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def pick_contracts(master: Sequence[Mapping[str, Any]], symbols: Sequence[str], today: date, min_days: int = 2) -> list[dict[str, Any]]:
    """Near and next month futures for the stock `symbols` plus the four index futures, from the Upstox instrument master."""
    want = {s.upper() for s in symbols}
    by_sym: dict[str, list[tuple[date, Mapping[str, Any]]]] = {}
    for r in master:
        if r.get("segment") != "NSE_FO" or r.get("instrument_type") != "FUT":
            continue
        sym = str(r.get("underlying_symbol") or "").upper()
        if sym not in want and sym not in INDEX_FUTURES:
            continue
        try:
            exp = datetime.fromtimestamp(float(r["expiry"]) / 1000.0, IST).date()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if exp >= today:
            by_sym.setdefault(sym, []).append((exp, r))
    out: list[dict[str, Any]] = []
    for sym, items in by_sym.items():
        kind = "IDX" if sym in INDEX_FUTURES else "STK"
        items.sort(key=lambda x: x[0])
        usable = [x for x in items if kind == "IDX" or (x[0] - today).days >= min_days]
        for label, (exp, r) in zip(("NEAR", "NEXT"), usable[:2]):
            out.append({"symbol": sym, "kind": kind, "contract": label, "expiry": exp.isoformat(), "dte": (exp - today).days, "lot": int(_f(r.get("lot_size"))),
                        "key": r["instrument_key"], "spot_key": r.get("underlying_key") or ""})
    return out


def rows_from_quotes(contracts: Sequence[Mapping[str, Any]], quotes: Mapping[str, Mapping[str, Any]], stamp: str) -> list[dict[str, Any]]:
    """quotes: instrument_key -> normalised quote (UpstoxClient._normalise_quote). Contracts with no quote are skipped; a missing spot leaves basis blank."""
    rows: list[dict[str, Any]] = []
    for c in contracts:
        q = quotes.get(c["key"])
        if not q or _f(q.get("last_price")) <= 0:
            continue
        spot = _f((quotes.get(c["spot_key"]) or {}).get("last_price"))
        ltp = _f(q["last_price"])
        ohlc = q.get("ohlc") or {}
        depth = q.get("depth") or {}
        bid = (depth.get("buy") or [{}])[0] if depth else {}
        ask = (depth.get("sell") or [{}])[0] if depth else {}
        rows.append({"captured_at": stamp, "symbol": c["symbol"], "kind": c["kind"], "contract": c["contract"], "expiry": c["expiry"], "dte": c["dte"], "lot": c["lot"],
                     "fut_ltp": ltp, "spot": spot or "", "basis_pct": round((ltp / spot - 1) * 100, 4) if spot > 0 else "", "oi": int(_f(q.get("oi"))),
                     "volume": int(_f(q.get("volume"))), "avg_price": _f(q.get("average_price")) or "", "buy_qty": int(_f(q.get("buy_quantity"))), "sell_qty": int(_f(q.get("sell_quantity"))),
                     "prev_close": _f(ohlc.get("close")) or "", "open": _f(ohlc.get("open")) or "", "high": _f(ohlc.get("high")) or "", "low": _f(ohlc.get("low")) or "",
                     "bid": _f(bid.get("price")) or "", "bid_qty": int(_f(bid.get("quantity"))) if bid else "", "ask": _f(ask.get("price")) or "", "ask_qty": int(_f(ask.get("quantity"))) if ask else ""})
    vix = quotes.get(VIX_KEY)
    if vix and _f(vix.get("last_price")) > 0:
        o = vix.get("ohlc") or {}
        rows.append({"captured_at": stamp, "symbol": "INDIAVIX", "kind": "VIX", "spot": _f(vix["last_price"]), "prev_close": _f(o.get("close")) or "",
                     "open": _f(o.get("open")) or "", "high": _f(o.get("high")) or "", "low": _f(o.get("low")) or ""})
    return rows


def append_rows(folder: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{date.today().isoformat()}.csv.gz"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    if not path.exists():
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "at", encoding="utf-8", newline="") as h:
        h.write(buf.getvalue())


def fetch_quotes(client: Any, keys: Sequence[str]) -> dict[str, dict[str, Any]]:
    """One quote call per batch; the answer is matched back by instrument_token so the response's own key naming does not matter."""
    out: dict[str, dict[str, Any]] = {}
    size = client.batch_size
    for i in range(0, len(keys), size):
        body = client._get("/v2/market-quote/quotes", {"instrument_key": ",".join(keys[i:i + size])}, auth=True)
        for _name, item in (body.get("data") or {}).items():
            if isinstance(item, Mapping) and item.get("instrument_token"):
                out[str(item["instrument_token"])] = client._normalise_quote(item)
    return out


def capture(client: Any, contracts: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int, str]:
    keys = sorted({c["key"] for c in contracts} | {c["spot_key"] for c in contracts if c["spot_key"]} | {VIX_KEY})
    stamp = datetime.now(IST).replace(microsecond=0).isoformat()
    try:
        quotes = fetch_quotes(client, keys)
    except Exception as exc:                                # noqa: BLE001 - the next minute tries again
        return [], len(contracts), f"{type(exc).__name__}: {str(exc)[:120]}"
    rows = rows_from_quotes(contracts, quotes, stamp)
    return rows, len(contracts) - sum(1 for r in rows if r["kind"] != "VIX"), ""


def run(root: Path = ROOT, once: bool = False, symbols: list[str] | None = None, out_root: Path | None = None) -> int:
    sys.path.insert(0, str(root))
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    from core.upstox_client import UpstoxClient
    from order_book_recorder import _universe

    if not os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip():
        print("UPSTOX_ANALYTICS_TOKEN is not set")
        return 2
    uni = sorted(_universe())
    if symbols:
        uni = [s for s in uni if s in set(symbols)]
    cycle = float(os.getenv("APLUS_FUTURES_SECONDS", "60") or 60)
    min_days = int(os.getenv("APLUS_FUTURES_MIN_DAYS", "2") or 2)
    base = out_root or root / "data" / "futures"
    client = UpstoxClient()
    contracts = pick_contracts(client._load_master(), uni, date.today(), min_days)
    if not contracts:
        print("no futures found in the instrument master")
        return 2
    end = datetime.now(IST).replace(hour=END[0], minute=END[1], second=0, microsecond=0)
    cycles = 0
    while True:
        t0 = time.monotonic()
        rows, failed, err = capture(client, contracts)
        append_rows(base, rows)
        cycles += 1
        health = {"day": date.today().isoformat(), "updated": datetime.now(IST).isoformat(timespec="seconds"), "contracts": len(contracts), "contracts_ok": len(contracts) - failed,
                  "rows_last_cycle": len(rows), "cycles": cycles, "seconds_last_cycle": round(time.monotonic() - t0, 1), "last_error": err}
        try:
            base.mkdir(parents=True, exist_ok=True)
            (base / "health.json").write_text(json.dumps(health), encoding="utf-8")
        except OSError:
            pass
        print(json.dumps(health), flush=True)
        if once or datetime.now(IST) >= end:
            return 0
        time.sleep(60 if failed == len(contracts) else max(1.0, cycle - (time.monotonic() - t0)))
        if datetime.now(IST) >= end:
            return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--force", action="store_true", help="run outside 09:13-15:30 or on a non-trading day")
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    if not a.once and not a.force:
        sys.path.insert(0, str(ROOT))
        from trading_calendar import is_trading_day

        now = datetime.now(IST)
        if not is_trading_day(now.date())[0]:
            print("not a trading day")
            return 0
        if now.hour * 60 + now.minute >= END[0] * 60 + END[1]:
            print("market over")
            return 0
        start = now.replace(hour=START[0], minute=START[1], second=0, microsecond=0)
        if now < start:
            time.sleep((start - now).total_seconds())
    out = Path(a.out) if a.out else (Path(tempfile.mkdtemp(prefix="futures_")) if a.once else None)
    return run(ROOT, a.once, syms or None, out)


if __name__ == "__main__":
    raise SystemExit(main())
