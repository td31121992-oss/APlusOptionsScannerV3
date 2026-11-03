"""NSE daily data: delivery %, F&O end-of-day (OI, volume, premium turnover) and bulk / block deals, with a long-history backfill (DATA ONLY: nothing here trades).

Free public files from nsearchives.nseindia.com (no login), filtered to our 213 F&O stocks (plus the four index futures / options):

    delivery   sec_bhavdata_full_<DDMMYYYY>.csv     delivered quantity and delivery % per stock  (stock analysis: accumulation vs intraday churn)
    F&O        BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip     every future and option: OI, change in OI, volume, close, settle, lot size
    deals      bulk.csv / block.csv                  the latest session's bulk and block deals (who bought / sold, quantity, price); only the latest file exists, so deal history
               builds up from the day this runs (the historical-deals API is tried in --backfill and skipped when NSE refuses it)

    data/nse_daily/delivery/<day>.csv         one row per stock
    data/nse_daily/fo/<day>.csv.gz            one row per contract (futures and options of our universe)
    data/nse_daily/summary/<day>.csv          one row per stock: delivery + futures OI + call / put OI, volume, PCR and premium turnover
    data/nse_daily/stock_daily.csv            all summary days stacked (what nse_tags.py reads)
    data/nse_daily/deals/<day>_bulk.csv, <day>_block.csv

    python nse_daily_data.py --latest                  today (or the most recent trading day) - run after the close, bhavcopy appears about 17:30-18:30
    python nse_daily_data.py --backfill 250            the last 250 calendar-weekdays going back from yesterday (about one year); holidays simply have no file; safe to re-run
    python nse_daily_data.py --day 2026-10-22 [--force]

Premium turnover = contracts x lot size x CLOSING price, in Rs crore: an approximation (the bhavcopy has no average traded price; a contract that moved a lot during the day is mispriced by its close), good for comparing a stock with its own history.
Volumes are in contracts, open interest in units (shares). Checked on 22 Oct: contract volumes match our own 5-minute chain data (median 0.97), and our near-expiry +-8-strike premium is about 0.6-0.7x of this all-expiry figure.
Requests are paced (about one a second) and the server is never hit twice for a day that is already stored.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent
BASE = "https://nsearchives.nseindia.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
INDEX_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
PAUSE = 0.8
CR = 1e7
SUMMARY_FIELDS = ["day", "symbol", "close", "prev_close", "ttl_qty", "turnover_cr", "trades", "deliv_qty", "deliv_per", "fut_expiry", "fut_oi", "fut_oi_chg", "fut_close", "fut_settle",
                  "call_oi", "put_oi", "call_vol", "put_vol", "call_prem_cr", "put_prem_cr"]
FO_FIELDS = ["type", "symbol", "expiry", "strike", "opt", "open", "high", "low", "close", "settle", "prev_close", "underlying", "oi", "oi_chg", "volume", "value", "trades", "lot"]


def _f(v: Any) -> float:
    try:
        x = float(str(v).strip())
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def url_delivery(day: date) -> str:
    return f"{BASE}/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv"


def url_fo(day: date) -> str:
    return f"{BASE}/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"


def parse_delivery(text: str, symbols: Iterable[str]) -> list[dict[str, Any]]:
    """sec_bhavdata_full rows for EQ-series stocks in `symbols` (the file pads its headers and values with spaces)."""
    want = set(symbols)
    rows = []
    reader = csv.reader(io.StringIO(text))
    header = [h.strip().upper() for h in next(reader, [])]
    for r in reader:
        if len(r) != len(header):
            continue
        d = dict(zip(header, (x.strip() for x in r)))
        if d.get("SERIES") != "EQ" or d.get("SYMBOL") not in want:
            continue
        rows.append({"symbol": d["SYMBOL"], "close": _f(d.get("CLOSE_PRICE")), "prev_close": _f(d.get("PREV_CLOSE")), "ttl_qty": int(_f(d.get("TTL_TRD_QNTY"))),
                     "turnover_cr": round(_f(d.get("TURNOVER_LACS")) / 100.0, 2), "trades": int(_f(d.get("NO_OF_TRADES"))), "deliv_qty": int(_f(d.get("DELIV_QTY"))),
                     "deliv_per": _f(d.get("DELIV_PER"))})
    return rows


def parse_fo(zip_bytes: bytes, symbols: Iterable[str]) -> list[dict[str, Any]]:
    """Futures and options rows of our universe (and the index contracts) from the UDiFF F&O bhavcopy zip."""
    want = set(symbols) | set(INDEX_SYMBOLS)
    rows = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        reader = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8", newline=""))
        for r in reader:
            if r.get("TckrSymb") not in want or r.get("FinInstrmTp") not in ("STF", "STO", "IDF", "IDO"):
                continue
            rows.append({"type": r["FinInstrmTp"], "symbol": r["TckrSymb"], "expiry": r["XpryDt"], "strike": _f(r.get("StrkPric")), "opt": r.get("OptnTp") or "",
                         "open": _f(r.get("OpnPric")), "high": _f(r.get("HghPric")), "low": _f(r.get("LwPric")), "close": _f(r.get("ClsPric")), "settle": _f(r.get("SttlmPric")),
                         "prev_close": _f(r.get("PrvsClsgPric")), "underlying": _f(r.get("UndrlygPric")), "oi": int(_f(r.get("OpnIntrst"))), "oi_chg": int(_f(r.get("ChngInOpnIntrst"))),
                         "volume": int(_f(r.get("TtlTradgVol"))), "value": round(_f(r.get("TtlTrfVal")), 2), "trades": int(_f(r.get("TtlNbOfTxsExctd"))), "lot": int(_f(r.get("NewBrdLotQty")))})
    return rows


def summarise(day: str, delivery: Iterable[Mapping[str, Any]], fo: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per stock: delivery numbers plus the near-month future and the whole option book (all expiries) of that stock."""
    out: dict[str, dict[str, Any]] = {}
    for d in delivery:
        out[d["symbol"]] = {"day": day, "symbol": d["symbol"], **{k: d[k] for k in ("close", "prev_close", "ttl_qty", "turnover_cr", "trades", "deliv_qty", "deliv_per")}}
    futs: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in fo:
        if r["type"] not in ("STF", "STO"):
            continue
        s = out.setdefault(r["symbol"], {"day": day, "symbol": r["symbol"]})
        if r["type"] == "STF":
            futs[r["symbol"]].append(r)
            continue
        side = "call" if r["opt"] == "CE" else "put"
        s[f"{side}_oi"] = s.get(f"{side}_oi", 0) + r["oi"]
        s[f"{side}_vol"] = s.get(f"{side}_vol", 0) + r["volume"]
        s[f"{side}_prem_cr"] = round(s.get(f"{side}_prem_cr", 0.0) + r["volume"] * r["lot"] * r["close"] / CR, 4)
    for sym, items in futs.items():
        near = min(items, key=lambda r: r["expiry"])
        s = out[sym]
        s.update(fut_expiry=near["expiry"], fut_oi=near["oi"], fut_oi_chg=near["oi_chg"], fut_close=near["close"], fut_settle=near["settle"])
    return [out[k] for k in sorted(out)]


def parse_deals(text: str) -> list[dict[str, Any]]:
    """bulk.csv / block.csv rows: date, symbol, client, BUY / SELL, quantity, price (value in Rs crore added)."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        qty, px = _f(r.get("Quantity Traded")), _f(r.get("Trade Price / Wght. Avg. Price"))
        try:
            d = datetime.strptime(r["Date"], "%d-%b-%Y").date().isoformat()
        except (KeyError, ValueError):
            continue
        rows.append({"day": d, "symbol": r.get("Symbol", ""), "client": r.get("Client Name", ""), "side": r.get("Buy/Sell", "").upper(), "qty": int(qty), "price": px, "value_cr": round(qty * px / CR, 3)})
    return rows


class Fetcher:
    def __init__(self, pause: float = PAUSE) -> None:
        import requests

        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "*/*"})
        self.pause, self._last = pause, 0.0

    def get(self, url: str) -> bytes | None:
        """The file's bytes, or None when NSE has none for that day (holiday / not yet published)."""
        wait = self.pause - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=60)
                self._last = time.time()
                if r.status_code == 200 and r.content:
                    return r.content
                if r.status_code in (403, 404):
                    return None
            except Exception:                              # noqa: BLE001 - network hiccup: retry
                pass
            time.sleep(2 * (attempt + 1))
        return None


def universe_symbols() -> list[str]:
    sys.path.insert(0, str(ROOT))
    from order_book_recorder import _universe

    return sorted(_universe())


def day_paths(root: Path, day: str) -> dict[str, Path]:
    base = root / "data" / "nse_daily"
    return {"delivery": base / "delivery" / f"{day}.csv", "fo": base / "fo" / f"{day}.csv.gz", "summary": base / "summary" / f"{day}.csv"}


def _write_csv(path: Path, fields: list[str], rows: Iterable[Mapping[str, Any]], gz: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = (lambda p: gzip.open(p, "wt", encoding="utf-8", newline="")) if gz else (lambda p: open(p, "w", encoding="utf-8", newline=""))
    with opener(path) as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def process_day(fetcher: Fetcher, day: date, symbols: list[str], root: Path = ROOT, force: bool = False) -> str:
    """Download and store one day. Returns 'stored', 'exists', 'no file' (holiday / not published) or 'partial'."""
    ds = day.isoformat()
    p = day_paths(root, ds)
    if p["summary"].exists() and not force:
        return "exists"
    raw_d = fetcher.get(url_delivery(day))
    raw_f = fetcher.get(url_fo(day))
    if raw_d is None and raw_f is None:
        return "no file"
    delivery = parse_delivery(raw_d.decode("utf-8", errors="replace"), symbols) if raw_d else []
    fo = parse_fo(raw_f, symbols) if raw_f else []
    if delivery:
        _write_csv(p["delivery"], ["symbol", "close", "prev_close", "ttl_qty", "turnover_cr", "trades", "deliv_qty", "deliv_per"], delivery)
    if fo:
        _write_csv(p["fo"], FO_FIELDS, fo, gz=True)
    _write_csv(p["summary"], SUMMARY_FIELDS, summarise(ds, delivery, fo))
    return "stored" if delivery and fo else "partial"


def build_stock_daily(root: Path = ROOT) -> Path:
    """Stack every summary/<day>.csv into stock_daily.csv (sorted by symbol, day)."""
    base = root / "data" / "nse_daily"
    rows = []
    for f in sorted((base / "summary").glob("*.csv")):
        with f.open(encoding="utf-8", newline="") as h:
            rows += list(csv.DictReader(h))
    rows.sort(key=lambda r: (r["symbol"], r["day"]))
    out = base / "stock_daily.csv"
    _write_csv(out, SUMMARY_FIELDS, rows)
    return out


def fetch_deals(fetcher: Fetcher, root: Path = ROOT) -> dict[str, int]:
    """Store the latest bulk and block deal files under the day each deal happened (re-running just refreshes that day)."""
    counts = {"bulk": 0, "block": 0}
    for kind in ("bulk", "block"):
        raw = fetcher.get(f"{BASE}/content/equities/{kind}.csv")
        if not raw:
            continue
        by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in parse_deals(raw.decode("utf-8", errors="replace")):
            by_day[r["day"]].append(r)
        for d, rows in by_day.items():
            _write_csv(root / "data" / "nse_daily" / "deals" / f"{d}_{kind}.csv", ["day", "symbol", "client", "side", "qty", "price", "value_cr"], rows)
            counts[kind] += len(rows)
    return counts


def weekdays_back(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--latest", action="store_true", help="today, plus the latest bulk / block deal files")
    ap.add_argument("--backfill", type=int, default=0, metavar="N", help="the last N weekdays before today")
    ap.add_argument("--day", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    symbols, fetcher = universe_symbols(), Fetcher()
    days: list[date] = []
    if a.day:
        days = [date.fromisoformat(a.day)]
    elif a.latest:
        days = [date.today()]
    elif a.backfill:
        days = weekdays_back(date.today() - timedelta(days=1), a.backfill)
    else:
        ap.print_help()
        return 1
    tally: dict[str, int] = defaultdict(int)
    for d in days:
        status = process_day(fetcher, d, symbols, ROOT, a.force)
        tally[status] += 1
        if status != "exists":
            print(d.isoformat(), status, flush=True)
    if a.latest or a.day:
        print("deals:", fetch_deals(fetcher))
    out = build_stock_daily()
    print("days:", dict(tally), "->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
