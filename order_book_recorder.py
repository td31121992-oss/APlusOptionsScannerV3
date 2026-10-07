"""Order-book recorder: once a minute, in market hours, save the buy/sell pressure of every F&O stock.

One read-only call to Dhan's marketfeed/quote per minute (all stocks in a single request, the same call the scanner
makes). Per stock and minute it stores last price, day volume, last trade size, total resting buy and sell quantity,
best bid/ask price and size, and the 5-level depth totals. Output: data/order_book/<date>.csv (about 8 MB a day).

Later this lets us test whether order-book imbalance and its change (buy vs sell pressure) predict short-term moves.
It cannot be back-filled, so the history starts the day this service starts. Never places orders; fails quietly.

Run:  python order_book_recorder.py      (the supervisor starts it with the other services)
"""

from __future__ import annotations

import csv
import os
import socket
import sys
import time
from datetime import datetime, time as clock
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
OUT = ROOT / "data" / "order_book"
LOCK_PORT = 8797
INTERVAL = 60
OPEN, CLOSE = clock(9, 15), clock(15, 31)
FIELDS = ["time", "symbol", "ltp", "volume", "last_qty", "buy_qty", "sell_qty", "bid", "bid_qty", "ask", "ask_qty",
          "depth_buy5", "depth_sell5", "imbalance", "avg_price"]


def _f(value: Any) -> float:
    try:
        out = float(value)
        return out if out == out else 0.0
    except (TypeError, ValueError):
        return 0.0


def book_row(symbol: str, quote: dict[str, Any], stamp: str) -> dict[str, Any]:
    depth = quote.get("depth") or {}
    buys, sells = depth.get("buy") or [], depth.get("sell") or []
    b1, s1 = (buys[0] if buys else {}), (sells[0] if sells else {})
    buy5 = sum(_f(x.get("quantity")) for x in buys)
    sell5 = sum(_f(x.get("quantity")) for x in sells)
    total = _f(quote.get("buy_quantity")) + _f(quote.get("sell_quantity"))
    imbalance = (_f(quote.get("buy_quantity")) - _f(quote.get("sell_quantity"))) / total if total > 0 else 0.0
    return {"time": stamp, "symbol": symbol, "ltp": _f(quote.get("last_price")), "volume": _f(quote.get("volume")),
            "last_qty": _f(quote.get("last_quantity")), "buy_qty": _f(quote.get("buy_quantity")),
            "sell_qty": _f(quote.get("sell_quantity")), "bid": _f(b1.get("price")), "bid_qty": _f(b1.get("quantity")),
            "ask": _f(s1.get("price")), "ask_qty": _f(s1.get("quantity")), "depth_buy5": buy5, "depth_sell5": sell5,
            "imbalance": round(imbalance, 4), "avg_price": _f(quote.get("average_price"))}


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and OPEN <= now.time() <= CLOSE


def append_rows(rows: list[dict[str, Any]], day: str, out_dir: Path = OUT) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)
    return path


def _universe() -> dict[str, int]:
    import pandas as pd

    master = pd.read_csv(ROOT / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                         usecols=["EXCH_ID", "SERIES", "SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL"])
    fno = set(master[master.INSTRUMENT == "OPTSTK"].UNDERLYING_SYMBOL.unique())
    eq = master[(master.EXCH_ID == "NSE") & (master.INSTRUMENT == "EQUITY") & (master.SERIES == "EQ")]
    eq = eq[eq.UNDERLYING_SYMBOL.isin(fno)].drop_duplicates("UNDERLYING_SYMBOL")
    return {str(s): int(i) for s, i in zip(eq.UNDERLYING_SYMBOL, eq.SECURITY_ID)}


def main() -> int:
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return 0                                         # another recorder is already running
    import requests
    from dotenv import load_dotenv

    sys.path.insert(0, str(ROOT))
    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token

    universe: dict[str, int] = {}
    by_id: dict[int, str] = {}
    session = requests.Session()
    while True:
        started = time.time()
        now = datetime.now(IST)
        try:
            if in_session(now):
                if not universe:
                    universe = _universe()
                    by_id = {v: k for k, v in universe.items()}
                cid = os.getenv("DHAN_CLIENT_ID", "").strip()
                token = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
                response = session.post("https://api.dhan.co/v2/marketfeed/quote", timeout=20, json={"NSE_EQ": list(universe.values())},
                                        headers={"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"})
                if response.status_code == 200:
                    data = (response.json().get("data") or {}).get("NSE_EQ") or {}
                    stamp = now.replace(microsecond=0).isoformat()
                    rows = [book_row(by_id.get(int(k), str(k)), v, stamp) for k, v in data.items() if v]
                    if rows:
                        append_rows(rows, now.date().isoformat())
        except Exception:                                # noqa: BLE001 - recorder must never crash the supervisor loop
            pass
        time.sleep(max(5.0, INTERVAL - (time.time() - started)))


if __name__ == "__main__":
    raise SystemExit(main())
