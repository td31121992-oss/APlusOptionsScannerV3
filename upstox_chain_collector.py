"""Upstox option-chain collector for ALL F&O stocks (DATA ONLY - never touches the scanner or any trade).

Every CYCLE_SECONDS (default 300) it takes the nearest-expiry option chain of every F&O stock from Upstox (free; bid/ask with quantities, OI and previous OI,
IV and greeks) and keeps the strikes within +-STRIKES of the money.

    data/options_intelligence_upstox/<day>/option_chain_rows.csv.gz     one row per leg per capture (columns below)
    data/options_intelligence_upstox/health.json                          cycles, symbols ok / failed, last capture, last error

    python upstox_chain_collector.py              run until 15:30 on trading days
    python upstox_chain_collector.py --once [--symbols TCS,INFY] [--out DIR]    one pass (for a test), writes to --out (default a temp folder)

Needs UPSTOX_ANALYTICS_TOKEN in .env. Symbols: all F&O stocks the Dhan master lists (same universe as the order-book recorder). Settings: APLUS_UPSTOX_CHAIN_STRIKES (8),
APLUS_UPSTOX_CHAIN_SECONDS (300), APLUS_UPSTOX_CHAIN_THREADS (4).
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
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
FIELDS = ["captured_at", "symbol", "underlying_security_id", "expiry", "spot", "strike", "side", "option_security_id", "ltp", "oi", "previous_oi", "oi_change", "volume", "iv",
          "delta", "gamma", "theta", "vega", "pop", "bid", "bid_qty", "ask", "ask_qty", "previous_close"]
START, END = (9, 14), (15, 30)


def rows_from_chain(symbol: str, sid: Any, chain: dict[str, Any], captured_at: str, strikes: int) -> list[dict[str, Any]]:
    """Flatten a normalised chain (UpstoxClient.get_option_chain) to leg rows, keeping `strikes` listed strikes either side of the money."""
    rows = chain.get("rows") or []
    spot = float(chain.get("underlying_ltp") or 0)
    if not rows or spot <= 0:
        return []
    ordered = sorted(rows, key=lambda r: r["strike"])
    i = min(range(len(ordered)), key=lambda k: abs(ordered[k]["strike"] - spot))
    out = []
    for r in ordered[max(0, i - strikes): i + strikes + 1]:
        for side, leg in (("CE", r.get("ce")), ("PE", r.get("pe"))):
            if not leg:
                continue
            out.append({"captured_at": captured_at, "symbol": symbol, "underlying_security_id": sid, "expiry": chain.get("expiry"), "spot": spot, "strike": r["strike"],
                        "side": side, "option_security_id": leg["security_id"], "ltp": leg["ltp"], "oi": leg["oi"], "previous_oi": leg["previous_oi"],
                        "oi_change": leg["oi"] - leg["previous_oi"] if leg["previous_oi"] else 0, "volume": leg["volume"], "iv": leg["iv"], "delta": leg["delta"],
                        "gamma": leg["gamma"], "theta": leg["theta"], "vega": leg["vega"], "pop": leg["pop"], "bid": leg["bid"], "bid_qty": leg["bid_qty"],
                        "ask": leg["ask"], "ask_qty": leg["ask_qty"], "previous_close": leg["previous_close"]})
    return out


def append_rows(folder: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "option_chain_rows.csv.gz"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    if not path.exists():
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "at", encoding="utf-8", newline="") as h:      # appended as a new gzip member; readers see one continuous file
        h.write(buf.getvalue())


def capture(client: Any, universe: dict[str, int], strikes: int, threads: int, expiries: dict[str, str]) -> tuple[list[dict[str, Any]], int, str]:
    stamp = datetime.now(IST).replace(microsecond=0).isoformat()
    failed, last_error = 0, ""

    def one(item: tuple[str, int]) -> list[dict[str, Any]]:
        sym, sid = item
        ch = client.get_option_chain(sid, expiries.get(sym))
        expiries[sym] = ch["expiry"]
        return rows_from_chain(sym, sid, ch, stamp, strikes)

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, threads)) as pool:
        futures = [(s, pool.submit(one, (s, i))) for s, i in universe.items()]
        for sym, f in futures:
            try:
                rows += f.result()
            except Exception as exc:                       # noqa: BLE001 - one stock failing must not stop the pass
                failed += 1
                last_error = f"{sym}: {type(exc).__name__}: {str(exc)[:100]}"
    return rows, failed, last_error


def run(root: Path = ROOT, once: bool = False, symbols: list[str] | None = None, out_root: Path | None = None) -> int:
    sys.path.insert(0, str(root))
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    from core.upstox_client import UpstoxClient
    from order_book_recorder import _universe

    if not os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip():
        print("UPSTOX_ANALYTICS_TOKEN is not set")
        return 2
    uni = _universe()
    if symbols:
        uni = {s: uni[s] for s in symbols if s in uni}
    if not uni:
        print("no symbols")
        return 2
    strikes = int(os.getenv("APLUS_UPSTOX_CHAIN_STRIKES", "8") or 8)
    cycle = float(os.getenv("APLUS_UPSTOX_CHAIN_SECONDS", "300") or 300)
    threads = int(os.getenv("APLUS_UPSTOX_CHAIN_THREADS", "4") or 4)
    base = out_root or root / "data" / "options_intelligence_upstox"
    client = UpstoxClient()
    expiries: dict[str, str] = {}
    cycles = 0
    end = datetime.now(IST).replace(hour=END[0], minute=END[1], second=0, microsecond=0)
    while True:
        t0 = time.monotonic()
        rows, failed, err = capture(client, uni, strikes, threads, expiries)
        append_rows(base / date.today().isoformat(), rows)
        cycles += 1
        health = {"day": date.today().isoformat(), "updated": datetime.now(IST).isoformat(timespec="seconds"), "symbols": len(uni), "symbols_ok": len(uni) - failed,
                  "symbols_failed": failed, "rows_last_cycle": len(rows), "cycles": cycles, "seconds_last_cycle": round(time.monotonic() - t0, 1), "last_error": err}
        try:
            base.mkdir(parents=True, exist_ok=True)
            (base / "health.json").write_text(json.dumps(health), encoding="utf-8")
        except OSError:
            pass
        print(json.dumps(health), flush=True)
        if once or datetime.now(IST) >= end:
            return 0
        if failed == len(uni):                              # nothing worked (token rejected, outage): wait longer before trying again
            time.sleep(60)
        time.sleep(max(1.0, cycle - (time.monotonic() - t0)))
        if datetime.now(IST) >= end:
            return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--force", action="store_true", help="run outside 09:14-15:30 or on a non-trading day")
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
    out = Path(a.out) if a.out else (Path(tempfile.mkdtemp(prefix="upstox_chain_")) if a.once else None)
    return run(ROOT, a.once, syms or None, out)


if __name__ == "__main__":
    raise SystemExit(main())
