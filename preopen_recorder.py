"""Pre-open session recorder (DATA ONLY: never touches the scanner or any trade).

NSE runs a pre-open auction from 09:00 to 09:08 in which every F&O stock gets an indicative opening price (IEP), the quantity that would trade at it and the buy / sell quantity queued.
Our other recorders start at 09:15, so the gap and the opening-auction pressure were not recorded. This polls NSE's public pre-open feed (the 213 F&O stocks) every PERIOD seconds from 08:59
to 09:16 and keeps every new snapshot:

    data/preopen/<day>.csv.gz        one row per stock per snapshot (columns below)
    data/preopen/<day>_final.csv     the last snapshot of the pre-open session (what nse_tags.py reads for the po_ tags)
    data/preopen/health.json         polls, snapshots, last snapshot time, last error

    iep          indicative equilibrium price       gap_pct   IEP vs previous close, %       final_qty   quantity that would trade at the IEP
    turnover_cr  Rs crore at the IEP                buy_qty / sell_qty   total queued;  imbalance = (buy - sell) / (buy + sell)       ato_buy / ato_sell   at-the-open orders

    python preopen_recorder.py            run 08:59-09:16 on trading days (scheduled task APlus_PreOpen_Recorder)
    python preopen_recorder.py --once     fetch one snapshot now (outside the session NSE returns the last session's final snapshot)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
URL = "https://www.nseindia.com/api/market-data-pre-open?key=FO"
HOME = "https://www.nseindia.com/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PERIOD = 20.0
START, END = (8, 59), (9, 16)
FINAL_BY = "09:13:00"                                    # snapshots up to here belong to the pre-open session (09:08 close, order matching to ~09:12)
FIELDS = ["captured_at", "symbol", "iep", "prev_close", "gap_pct", "final_qty", "turnover_cr", "buy_qty", "sell_qty", "imbalance", "ato_buy", "ato_sell", "levels"]


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def parse(payload: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """(snapshot time as 'YYYY-MM-DDTHH:MM:SS', rows) from the pre-open JSON."""
    ts = str(payload.get("timestamp") or "")
    try:
        when = datetime.strptime(ts, "%d-%b-%Y %H:%M:%S").isoformat()
    except ValueError:
        when = datetime.now(IST).replace(tzinfo=None).isoformat(timespec="seconds")
    rows = []
    for item in payload.get("data") or []:
        m = item.get("metadata") or {}
        pm = (item.get("detail") or {}).get("preOpenMarket") or {}
        buy, sell = _f(pm.get("totalBuyQuantity")), _f(pm.get("totalSellQuantity"))
        rows.append({"captured_at": when, "symbol": m.get("symbol", ""), "iep": _f(pm.get("IEP") or m.get("iep")), "prev_close": _f(m.get("previousClose") or pm.get("prevClose")),
                     "gap_pct": _f(m.get("pChange") if m.get("pChange") is not None else pm.get("perChange")), "final_qty": int(_f(pm.get("finalQuantity") or m.get("finalQuantity"))),
                     "turnover_cr": round(_f(m.get("totalTurnover")) / 1e7, 3), "buy_qty": int(buy), "sell_qty": int(sell),
                     "imbalance": round((buy - sell) / (buy + sell), 3) if buy + sell > 0 else "", "ato_buy": int(_f(pm.get("atoBuyQty"))), "ato_sell": int(_f(pm.get("atoSellQty"))),
                     "levels": len(pm.get("preopen") or [])})
    return when, [r for r in rows if r["symbol"]]


def append_snapshot(root: Path, day: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    folder = root / "data" / "preopen"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv.gz"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    if not path.exists():
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "at", encoding="utf-8", newline="") as h:
        h.write(buf.getvalue())


def write_final(root: Path, day: str, rows: list[dict[str, Any]]) -> None:
    folder = root / "data" / "preopen"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{day}_final.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


class Poller:
    def __init__(self) -> None:
        import requests

        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": HOME})
        self.primed = 0.0

    def fetch(self) -> dict[str, Any]:
        if time.time() - self.primed > 600:                  # NSE wants the cookies from the home page first
            self.s.get(HOME, timeout=20)
            self.primed = time.time()
        r = self.s.get(URL, timeout=30)
        r.raise_for_status()
        return r.json()


def run(root: Path = ROOT, once: bool = False, out_root: Path | None = None) -> int:
    base = out_root or root
    poller = Poller()
    day = date.today().isoformat()
    end = datetime.now(IST).replace(hour=END[0], minute=END[1], second=0, microsecond=0)
    last_when, polls, snaps, err, final_rows = "", 0, 0, "", []
    while True:
        try:
            when, rows = parse(poller.fetch())
            polls += 1
            if rows and when != last_when:
                last_when = when
                snaps += 1
                append_snapshot(base, day if not once else when[:10], rows)
                if when[11:] <= FINAL_BY:
                    final_rows = rows
                    write_final(base, when[:10], rows)
            err = ""
        except Exception as exc:                              # noqa: BLE001 - try again next period
            err = f"{type(exc).__name__}: {str(exc)[:100]}"
        try:
            (base / "data" / "preopen").mkdir(parents=True, exist_ok=True)
            (base / "data" / "preopen" / "health.json").write_text(json.dumps({"day": day, "updated": datetime.now(IST).isoformat(timespec="seconds"), "polls": polls, "snapshots": snaps,
                                                                              "last_snapshot": last_when, "stocks": len(final_rows), "last_error": err}), encoding="utf-8")
        except OSError:
            pass
        print(f"polls {polls} snapshots {snaps} last {last_when} {err}", flush=True)
        if once or datetime.now(IST) >= end:
            return 0 if (snaps or once) else 1
        time.sleep(PERIOD)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--force", action="store_true", help="run outside 08:59-09:16 or on a non-trading day")
    a = ap.parse_args()
    if not a.once and not a.force:
        sys.path.insert(0, str(ROOT))
        from trading_calendar import is_trading_day

        now = datetime.now(IST)
        if not is_trading_day(now.date())[0]:
            print("not a trading day")
            return 0
        if now.hour * 60 + now.minute >= END[0] * 60 + END[1]:
            print("pre-open over")
            return 0
        start = now.replace(hour=START[0], minute=START[1], second=0, microsecond=0)
        if now < start:
            time.sleep((start - now).total_seconds())
    return run(ROOT, a.once, Path(a.out) if a.out else None)


if __name__ == "__main__":
    raise SystemExit(main())
