"""Resumable downloader for historical (expired) stock-option candles from Dhan.

Uses Dhan's 'rolling option' endpoint: for each stock, each 30-day window, each
side (CALL/PUT) and strike offset (ATM-N..ATM+N) it stores the raw response
(5-minute OHLC, volume, open interest, implied volatility, spot, strike) as
  <out>/<SYMBOL>/<window_start>/<exp>_<CE|PE>_<ATM+n>.json.gz
Every response is stored - even empty ones - so nothing is requested twice and
coverage gaps (Dhan's history is patchy) are recorded. Newest windows first, so a
partial run is still useful.

Safety: paces itself (--rps), never runs during weekday market hours (so it cannot
starve the live scanner of Dhan's shared rate limit), backs off on 429/5xx, stops on
auth failure or low disk, and holds a lock so only one instance runs.

    python download_expired_options.py --out E:\\APlusData\\expired_options --stop-at 08:30
    python download_expired_options.py --plan            # only print the plan/ETA
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import socket
import sys
import time
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
URL = "https://api.dhan.co/v2/charts/rollingoption"
WINDOW_DAYS = 30                      # the API rejects spans longer than 30 days
LOCK_PORT = 8796
REQUIRED = ["open", "high", "low", "close", "volume", "oi", "iv", "strike", "spot"]
MARKET_PAUSE = (clock_time(9, 0), clock_time(15, 45))   # weekdays: do not call Dhan data APIs


# ----------------------------------------------------------------------------- planning
def windows(since: date, until: date) -> list[tuple[date, date]]:
    """Consecutive 30-day windows covering [since, until], NEWEST first."""
    out, start = [], since
    while start <= until:
        end = min(start + timedelta(days=WINDOW_DAYS - 1), until)
        out.append((start, end))
        start = end + timedelta(days=1)
    return list(reversed(out))


def strike_label(offset: int) -> str:
    return "ATM" if offset == 0 else f"ATM{offset:+d}"


def file_for(out: Path, symbol: str, window_start: date, exp_code: int, side: str, offset: int) -> Path:
    return out / symbol / window_start.isoformat() / f"{exp_code}_{'CE' if side == 'CALL' else 'PE'}_{strike_label(offset)}.json.gz"


def tasks(out: Path, symbols: dict[str, int], wins, exp_codes, strikes: int) -> Iterator[dict]:
    """Yield pending request descriptors (newest window first, then symbol)."""
    offsets = sorted(range(-strikes, strikes + 1), key=lambda o: (abs(o), o))     # ATM first, then +/-1, ...
    for (w_start, w_end) in wins:
        for symbol, sec_id in symbols.items():
            for code in exp_codes:
                for side in ("CALL", "PUT"):
                    for off in offsets:
                        path = file_for(out, symbol, w_start, code, side, off)
                        if path.exists():
                            continue
                        yield {"symbol": symbol, "security_id": sec_id, "from": w_start, "to": w_end,
                               "exp_code": code, "side": side, "offset": off, "path": path}


def build_body(t: dict, interval: str = "5") -> dict:
    return {
        "exchangeSegment": "NSE_FNO", "interval": interval, "securityId": int(t["security_id"]), "instrument": "OPTSTK",
        "expiryFlag": "MONTH", "expiryCode": int(t["exp_code"]), "strike": strike_label(t["offset"]),
        "drvOptionType": t["side"], "requiredData": REQUIRED,
        "fromDate": t["from"].isoformat(), "toDate": t["to"].isoformat(),
    }


# ----------------------------------------------------------------------------- helpers
class AuthError(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, rps: float, clock=time.monotonic, sleep=time.sleep) -> None:
        self.interval = 1.0 / max(0.05, rps)
        self._clock, self._sleep, self._next = clock, sleep, 0.0

    def wait(self) -> None:
        now = self._clock()
        if now < self._next:
            self._sleep(self._next - now)
            now = self._next
        self._next = max(now, self._next) + self.interval


def in_market_pause(now: datetime) -> bool:
    return now.weekday() < 5 and MARKET_PAUSE[0] <= now.time() < MARKET_PAUSE[1]


def seconds_until_resume(now: datetime) -> int:
    resume = datetime.combine(now.date(), MARKET_PAUSE[1], IST)
    return max(60, int((resume - now).total_seconds()))


def write_atomic_gz(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    os.replace(tmp, path)


def candle_count(payload: dict, side: str) -> int:
    blk = ((payload or {}).get("data") or {}).get("ce" if side == "CALL" else "pe") or {}
    return len(blk.get("timestamp") or [])


def fetch(session, headers: dict, body: dict, sleep=time.sleep, max_attempts: int = 5) -> dict:
    """POST with retries. Returns {'status': http, 'payload': json|None}. Raises AuthError on 401/403."""
    last = {"status": 0, "payload": None}
    for attempt in range(1, max_attempts + 1):
        try:
            r = session.post(URL, headers=headers, json=body, timeout=60)
        except Exception as exc:  # noqa: BLE001 - network hiccup
            last = {"status": 0, "payload": {"error": type(exc).__name__}}
            sleep(2 * attempt)
            continue
        if r.status_code in (401, 403):
            raise AuthError(f"HTTP {r.status_code}")
        if r.status_code == 429 or r.status_code >= 500:
            last = {"status": r.status_code, "payload": None}
            print(f"  HTTP {r.status_code} (attempt {attempt}/{max_attempts}) - backing off {10 * attempt}s", flush=True)
            sleep(10 * attempt)
            continue
        try:
            payload = r.json()
        except ValueError:
            payload = {"error": "non-json", "text": r.text[:200]}
        return {"status": r.status_code, "payload": payload}
    return last


def load_universe(base: Path = ROOT) -> dict[str, int]:
    data = json.loads((base / "data" / "cache" / "instrument_universe.json").read_text(encoding="utf-8"))
    return {sym.upper(): int(v["security_id"]) for sym, v in sorted(data.items()) if v.get("security_id")}


def disk_free_gb(path: Path) -> float:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free / 1e9



def write_progress(out: Path, planned: int, stored_total: int, stats: dict, last: str) -> None:
    try:
        payload = {"updated_at": datetime.now(IST).isoformat(timespec="seconds"), "planned_total": planned,
                   "stored_total": stored_total, "pct": round(100 * stored_total / planned, 1) if planned else 0.0,
                   "with_data": stats["with_data"], "empty": stats["empty"], "errors": stats["errors"], "last": last}
        tmp = out / "_progress.json.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, out / "_progress.json")
    except OSError:
        pass

# ----------------------------------------------------------------------------- run
def run(args, session=None, headers_factory=None, now_fn=lambda: datetime.now(IST), sleep=time.sleep) -> dict:
    out = Path(args.out)
    symbols = load_universe()
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",")}
        symbols = {k: v for k, v in symbols.items() if k in wanted}
    wins = windows(args.since, args.until)
    exp_codes = [int(c) for c in str(args.expiry_codes).split(",")]
    pending = tasks(out, symbols, wins, exp_codes, args.strikes)

    if args.plan:
        total = len(symbols) * len(wins) * len(exp_codes) * 2 * (2 * args.strikes + 1)
        done = sum(1 for _ in out.rglob("*.json.gz")) if out.exists() else 0
        left = max(0, total - done)
        print(f"symbols {len(symbols)} | windows {len(wins)} ({wins[-1][0]} .. {wins[0][1]}) | strikes {2*args.strikes+1} | expiry codes {exp_codes}")
        print(f"total calls {total:,} | already stored {done:,} | remaining {left:,}")
        print(f"at {args.rps} calls/s: ~{left / args.rps / 3600:.1f} h of runtime (~{left / args.rps / 3600 / 15:.1f} nights of 15 h)")
        print(f"estimated size ~{total * 25 / 1e6:.1f} GB compressed")
        return {"planned": total, "remaining": left}

    stats = {"calls": 0, "stored": 0, "with_data": 0, "empty": 0, "errors": 0}
    planned = len(symbols) * len(wins) * len(exp_codes) * 2 * (2 * args.strikes + 1)
    stored_base = sum(1 for _ in out.rglob("*.json.gz")) if out.exists() else 0
    limiter = RateLimiter(args.rps, sleep=sleep)
    headers, token_at = None, 0.0
    stop_at = None
    if args.stop_at:
        hh, mm = map(int, args.stop_at.split(":"))
        stop_at = clock_time(hh, mm)

    for t in pending:
        now = now_fn()
        if args.max_calls and stats["calls"] >= args.max_calls:
            break
        if stop_at and now.time() >= stop_at and now.time() < clock_time(15, 0):
            print(f"stop-at {args.stop_at} reached"); break
        if not args.ignore_market_hours and in_market_pause(now):
            wait = seconds_until_resume(now)
            print(f"market hours - pausing {wait // 60} min"); sleep(wait)
            continue
        if stats["calls"] % 500 == 0 and disk_free_gb(out) < args.min_free_gb:
            print(f"low disk (<{args.min_free_gb} GB free) - stopping"); break
        if headers is None or time.time() - token_at > 1200:
            headers, token_at = headers_factory(), time.time()
        limiter.wait()
        try:
            res = fetch(session, headers, build_body(t, args.interval), sleep=sleep)
        except AuthError as exc:
            headers = headers_factory()                # one refresh attempt
            token_at = time.time()
            try:
                res = fetch(session, headers, build_body(t, args.interval), sleep=sleep)
            except AuthError:
                print(f"auth failure ({exc}) - stopping so the token can be refreshed"); break
        stats["calls"] += 1
        status, payload = res["status"], res["payload"]
        if status != 200:
            print(f"{now_fn():%H:%M:%S} non-200 ({status}) for {t['symbol']} {t['from']} {t['side']} {strike_label(t['offset'])}", flush=True)
        if status == 200 and payload is not None:
            n = candle_count(payload, t["side"])
            write_atomic_gz(t["path"], {"request": {k: str(v) for k, v in build_body(t, args.interval).items() if k != "requiredData"},
                                        "http": status, "candles": n, "response": payload})
            stats["stored"] += 1
            stats["with_data" if n else "empty"] += 1
        elif status == 400:                           # bad parameters for this combination: remember, never retry
            write_atomic_gz(t["path"], {"request": {"symbol": t["symbol"]}, "http": 400, "candles": 0, "response": payload})
            stats["stored"] += 1
            stats["errors"] += 1
        else:
            stats["errors"] += 1                      # transient: leave unwritten so a later run retries
        if stats["calls"] % 200 == 0:
            write_progress(out, planned, stored_base + stats["stored"], stats, f"{t['symbol']} {t['from']}")
            print(f"{now_fn():%H:%M:%S} calls {stats['calls']:,} stored {stats['stored']:,} data {stats['with_data']:,} empty {stats['empty']:,} errors {stats['errors']:,} | now {t['symbol']} {t['from']}")
    write_progress(out, planned, stored_base + stats["stored"], stats, "finished or stopped")
    return stats


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=r"E:\APlusData\expired_options")
    ap.add_argument("--since", type=date.fromisoformat, default=date(2021, 7, 1))
    ap.add_argument("--until", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--rps", type=float, default=2.0, help="calls per second (Dhan allows ~5; shared with the live scanner)")
    ap.add_argument("--strikes", type=int, default=3, help="strike offsets ATM-N..ATM+N")
    ap.add_argument("--expiry-codes", default="1", help="1 = near month, 2 = next month; comma separated")
    ap.add_argument("--interval", default="5", help="candle minutes: 1, 5, 15, 25, 60")
    ap.add_argument("--symbols", default="", help="comma separated subset")
    ap.add_argument("--stop-at", default="", help="HH:MM IST to stop (e.g. 08:30 for nightly runs)")
    ap.add_argument("--max-calls", type=int, default=0)
    ap.add_argument("--min-free-gb", type=float, default=8.0)
    ap.add_argument("--ignore-market-hours", action="store_true")
    ap.add_argument("--plan", action="store_true")
    return ap.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.plan:
        run(args)
        return 0
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        print("another downloader instance is already running")
        return 0
    import requests
    from dotenv import load_dotenv

    sys.path.insert(0, str(ROOT))
    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token

    def headers_factory() -> dict:
        cid = os.getenv("DHAN_CLIENT_ID", "").strip()
        tok = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
        return {"access-token": tok, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}

    Path(args.out).mkdir(parents=True, exist_ok=True)
    stats = run(args, session=requests.Session(), headers_factory=headers_factory)
    print("finished:", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
