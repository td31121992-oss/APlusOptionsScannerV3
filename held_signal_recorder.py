"""Held-signal option recorder (DATA ONLY - never touches the scanner or any trade).

The question it answers: what would the CALLS / PUTS on the setups the gates held back (or blocked) have cost and paid? Until now only the stock's own move could be studied for those setups
(23 Nov: TCS and POLICYBZR were held all morning and no option price for them exists anywhere), because option prices were only recorded for options we actually traded.

Once a minute in market hours it reads today's data/signal_snapshots/<day>.csv. The FIRST signal of each stock and side (before 14:30) in each of these groups is tracked:

    PASSED          passed all gates (so the comparison with the held-back ones is on the same days and the same rows)
    EXTENDED_WAIT   held as late / overheated / overextended          OTHER_WAIT   any other A+ wait          V2_BLOCK   blocked by the V2 stock selection

For a tracked signal it picks two contracts of the right side at the signal: the at-the-money strike (nearest to the stock price at the signal) and the first strike in the money, both of the nearest
expiry that is at least APLUS_HELD_MIN_DAYS (2) away (what the scanner's real trades use). Every minute until 15:20 it saves each contract's bid, ask, last price, volume and open interest, and the
stock's price, from the Upstox analytics token (one or two batched quote calls a minute, priority "floor").

    data/held_signal_options/<day>.csv.gz   one row per contract per minute (columns below)
    data/held_signal_options/health.json    cycles, signals tracked, contracts, last error

    entry for a replay = the ask of the first row at or after the signal; exit = the bid. 'signal_time' and 'signal_spot' are the snapshot's.

    python held_signal_recorder.py             run until 15:20 on trading days
    python held_signal_recorder.py --once [--day YYYY-MM-DD] [--out DIR]    one pass (for a test)
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
START, END = (9, 13), (15, 20)
LAST_SIGNAL = "14:30"
FIELDS = ["captured_at", "symbol", "direction", "group", "status", "signal_time", "signal_spot", "kind", "side", "strike", "expiry", "lot", "ltp", "bid", "bid_qty", "ask", "ask_qty",
          "volume", "oi", "spot"]
GROUPS = ("PASSED", "EXTENDED_WAIT", "OTHER_WAIT", "V2_BLOCK")


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def group_of(status: str) -> str:
    s = str(status)
    if s == "PASSED_ALL_GATES":
        return "PASSED"
    if s.startswith("A_PLUS_WAIT_LATE_") or s == "A_PLUS_WAIT_OVEREXTENDED":
        return "EXTENDED_WAIT"
    if s.startswith("A_PLUS_WAIT"):
        return "OTHER_WAIT"
    if s.startswith("V2_STOCK"):
        return "V2_BLOCK"
    return "OTHER"


def index_options(master: Sequence[Mapping[str, Any]], symbols: set[str] | None = None) -> dict[str, dict[tuple[str, str], list[tuple[float, str, int]]]]:
    """underlying -> (expiry iso, 'CE'/'PE') -> sorted [(strike, instrument_key, lot)], from the Upstox instrument master."""
    out: dict[str, dict[tuple[str, str], list[tuple[float, str, int]]]] = {}
    for r in master:
        if r.get("segment") != "NSE_FO" or r.get("instrument_type") not in ("CE", "PE"):
            continue
        sym = str(r.get("underlying_symbol") or "").upper()
        if symbols is not None and sym not in symbols:
            continue
        try:
            exp = datetime.fromtimestamp(float(r["expiry"]) / 1000.0, IST).date().isoformat()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        out.setdefault(sym, {}).setdefault((exp, r["instrument_type"]), []).append((_f(r.get("strike_price")), r["instrument_key"], int(_f(r.get("lot_size")))))
    for per in out.values():
        for lst in per.values():
            lst.sort()
    return out


def pick_contracts(options: Mapping[tuple[str, str], Sequence[tuple[float, str, int]]], direction: str, spot: float, today: date, min_days: int = 2) -> list[dict[str, Any]]:
    """The at-the-money and the first in-the-money strike of the right side, nearest expiry at least `min_days` away. [] when there is none."""
    side = "CE" if str(direction).upper() == "BULLISH" else "PE"
    expiries = sorted({e for (e, s) in options if s == side and (date.fromisoformat(e) - today).days >= min_days})
    if not expiries or spot <= 0:
        return []
    strikes = list(options[(expiries[0], side)])
    if not strikes:
        return []
    i = min(range(len(strikes)), key=lambda k: abs(strikes[k][0] - spot))
    j = i - 1 if side == "CE" else i + 1                                   # in the money: a lower strike for a call, a higher one for a put
    picks = [("ATM", strikes[i])] + ([("ITM1", strikes[j])] if 0 <= j < len(strikes) else [])
    return [{"kind": k, "side": side, "strike": s[0], "key": s[1], "lot": s[2], "expiry": expiries[0]} for k, s in picks]


def new_signals(rows: Sequence[Mapping[str, Any]], tracked: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """The first signal per stock and side (before LAST_SIGNAL, in a group we track) that is not tracked yet. rows are snapshot rows in time order."""
    out: list[dict[str, Any]] = []
    seen = set(tracked)
    for r in rows:
        key = (str(r.get("symbol") or "").upper(), str(r.get("direction") or "").upper())
        grp = group_of(r.get("status") or "")
        hhmm = str(r.get("time") or "")[11:16]
        if key in seen or grp not in GROUPS or not key[0] or key[1] not in ("BULLISH", "BEARISH") or not hhmm or hhmm >= LAST_SIGNAL:
            continue
        seen.add(key)
        out.append({"symbol": key[0], "direction": key[1], "group": grp, "status": r.get("status"), "time": str(r.get("time"))[:19], "spot": _f(r.get("ltp"))})
    return out


def rows_from_quotes(tracked: Sequence[Mapping[str, Any]], quotes: Mapping[str, Mapping[str, Any]], stamp: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in tracked:
        spot = _f((quotes.get(t["spot_key"]) or {}).get("last_price")) if t.get("spot_key") else 0.0
        for c in t["contracts"]:
            q = quotes.get(c["key"])
            if not q:
                continue
            depth = q.get("depth") or {}
            bid = (depth.get("buy") or [{}])[0] if depth else {}
            ask = (depth.get("sell") or [{}])[0] if depth else {}
            rows.append({"captured_at": stamp, "symbol": t["symbol"], "direction": t["direction"], "group": t["group"], "status": t["status"], "signal_time": t["time"], "signal_spot": t["spot"] or "",
                         "kind": c["kind"], "side": c["side"], "strike": c["strike"], "expiry": c["expiry"], "lot": c["lot"], "ltp": _f(q.get("last_price")) or "",
                         "bid": _f(bid.get("price")) or "", "bid_qty": int(_f(bid.get("quantity"))) if bid else "", "ask": _f(ask.get("price")) or "",
                         "ask_qty": int(_f(ask.get("quantity"))) if ask else "", "volume": int(_f(q.get("volume"))), "oi": int(_f(q.get("oi"))), "spot": spot or ""})
    return rows


def append_rows(folder: Path, rows: Sequence[Mapping[str, Any]], day: str) -> None:
    if not rows:
        return
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv.gz"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    if not path.exists():
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "at", encoding="utf-8", newline="") as h:
        h.write(buf.getvalue())


def read_signals(root: Path, day: str) -> list[dict[str, str]]:
    path = root / "data" / "signal_snapshots" / f"{day}.csv"
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as h:
            return list(csv.DictReader(h))
    except OSError:
        return []


def run(root: Path = ROOT, once: bool = False, day: str | None = None, out_root: Path | None = None) -> int:
    sys.path.insert(0, str(root))
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    from core.upstox_client import UpstoxClient
    from futures_recorder import fetch_quotes

    if not os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip():
        print("UPSTOX_ANALYTICS_TOKEN is not set")
        return 2
    today = date.fromisoformat(day) if day else date.today()
    min_days = int(os.getenv("APLUS_HELD_MIN_DAYS", "2") or 2)
    base = out_root or root / "data" / "held_signal_options"
    client = UpstoxClient(priority="floor")                  # one or two batched calls a minute, with its own small reserve
    master = client._load_master()
    spot_keys = {str(r.get("underlying_symbol") or "").upper(): r.get("underlying_key") or "" for r in master if r.get("segment") == "NSE_FO" and r.get("instrument_type") == "CE"}
    options: dict[str, Any] | None = None
    tracked: list[dict[str, Any]] = []
    done: set[tuple[str, str]] = set()
    end = datetime.now(IST).replace(hour=END[0], minute=END[1], second=0, microsecond=0)
    cycles, last_error = 0, ""
    while True:
        t0 = time.monotonic()
        for s in new_signals(read_signals(root, today.isoformat()), done):
            done.add((s["symbol"], s["direction"]))
            if options is None:
                options = index_options(master)
            picks = pick_contracts(options.get(s["symbol"], {}), s["direction"], s["spot"], today, min_days)
            if picks:
                tracked.append({**s, "contracts": picks, "spot_key": spot_keys.get(s["symbol"], "")})
        keys = sorted({c["key"] for t in tracked for c in t["contracts"]} | {t["spot_key"] for t in tracked if t["spot_key"]})
        rows: list[dict[str, Any]] = []
        if keys:
            stamp = datetime.now(IST).replace(microsecond=0).isoformat()
            try:
                rows = rows_from_quotes(tracked, fetch_quotes(client, keys), stamp)
                last_error = ""
            except Exception as exc:                          # noqa: BLE001 - the next minute tries again
                last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
        append_rows(base, rows, today.isoformat())
        cycles += 1
        health = {"day": today.isoformat(), "updated": datetime.now(IST).isoformat(timespec="seconds"), "signals_tracked": len(tracked), "contracts": sum(len(t["contracts"]) for t in tracked),
                  "rows_last_cycle": len(rows), "cycles": cycles, "last_error": last_error}
        try:
            base.mkdir(parents=True, exist_ok=True)
            (base / "health.json").write_text(json.dumps(health), encoding="utf-8")
        except OSError:
            pass
        print(json.dumps(health), flush=True)
        if once or datetime.now(IST) >= end:
            return 0
        time.sleep(max(1.0, 60 - (time.monotonic() - t0)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--day", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.once:
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
    out = Path(a.out) if a.out else (Path(tempfile.mkdtemp(prefix="held_signals_")) if a.once else None)
    return run(ROOT, a.once, a.day or None, out)


if __name__ == "__main__":
    raise SystemExit(main())
