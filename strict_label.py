"""Strict outcome label for every signal (research only; no trading effect).

For each signal in data/missed_opportunities/<day>/signals.csv (traded, A+-held, V2-blocked, ... - every first signal of a stock and side) it takes the
option we would have bought, from Upstox 1-minute option candles, and asks the question that matters:

    does the option reach +TARGET% BEFORE it falls -STOP%?      (default +10% / -20%, minute by minute; a minute that touches both counts as a stop)

The option is the listed strike about 0.5% in the money for the side (as the selector aims for), nearest expiry on or after the day. Entry price =
close of the last 1-minute candle at or before (signal time + delay) plus 1% slippage. Two entry delays: 1 minute after the signal ("at the signal")
and 10 minutes after (the median real wait between the first flag and our entry).

    data/strict_labels/<day>.csv       one row per signal and delay: contract, entry, hit10_first, minutes to +10%, stop_first, best / worst within 30 / 60 minutes and the day
    data/strict_labels/summary.md      hit rates by fate, side, delay and signal hour
    data/strict_labels/cache/          contract lists and candles already fetched (a re-run only fetches what is new)

    python strict_label.py [YYYY-MM-DD ...]         (all days that have signals when none are given)
"""

from __future__ import annotations

import csv
import glob
import json
import statistics as st
import sys
import time
import urllib.parse as up
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
TARGET, STOP, SLIP, ITM_PCT = 10.0, 20.0, 1.0, 0.5
DELAYS = (1, 10)
FIELDS = ["day", "symbol", "dir", "fate", "ready", "delay", "expiry", "strike", "spot", "entry", "hit10_first", "min_to_hit10", "stop_first", "min_to_stop", "best_30", "worst_30",
          "best_60", "worst_60", "best_day", "worst_day", "close_pct", "hit10_30", "hit10_60"]


def _mins(h: str) -> int | None:
    try:
        a, b = str(h).split(":")[:2]
        return int(a) * 60 + int(b)
    except (ValueError, AttributeError):
        return None


def label(bars: list[tuple[int, float, float, float, float]], minute: int, delay: int, target: float = TARGET, stop: float = STOP, slip: float = SLIP) -> dict[str, Any] | None:
    """bars = (minute_of_day, open, high, low, close), ascending. None when there is no price at/before the entry minute or nothing after it."""
    at = [b for b in bars if b[0] <= minute + delay]
    after = [b for b in bars if at and b[0] > at[-1][0]]
    if not at or not after or at[-1][4] <= 0:
        return None
    t0 = at[-1][0]
    entry = at[-1][4] * (1 + slip / 100.0)
    up_px, dn_px = entry * (1 + target / 100.0), entry * (1 - stop / 100.0)
    hit = stopped = None
    for b in after:
        if b[3] <= dn_px:
            stopped = b[0] - t0
            break
        if b[2] >= up_px:
            hit = b[0] - t0
            break
    out: dict[str, Any] = {"entry": round(entry, 2), "hit10_first": int(hit is not None), "min_to_hit10": hit if hit is not None else "", "stop_first": int(stopped is not None),
                           "min_to_stop": stopped if stopped is not None else ""}
    for name, span in (("30", 30), ("60", 60), ("day", 10 ** 6)):
        win = [b for b in after if b[0] - t0 <= span]
        out[f"best_{name}"] = round((max(b[2] for b in win) / entry - 1) * 100, 1) if win else ""
        out[f"worst_{name}"] = round((min(b[3] for b in win) / entry - 1) * 100, 1) if win else ""
    out["close_pct"] = round((after[-1][4] / entry - 1) * 100, 1)
    out["hit10_30"] = int(hit is not None and hit <= 30)
    out["hit10_60"] = int(hit is not None and hit <= 60)
    return out


class Source:
    """Upstox contract lists and 1-minute candles with an on-disk cache and gentle pacing."""

    def __init__(self, root: Path = ROOT, client: Any = None, pause: float = 0.35) -> None:
        self.cache = root / "data" / "strict_labels" / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.pause = pause
        if client is None:
            from dotenv import load_dotenv

            load_dotenv(root / ".env")
            sys.path.insert(0, str(root))
            from core.upstox_client import UpstoxClient

            client = UpstoxClient()
        self.client = client
        self.calls = 0

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        from core.upstox_client import UpstoxLimit

        for attempt in range(6):
            try:
                time.sleep(self.pause)
                self.calls += 1
                return self.client._get(path, params, auth=True)
            except UpstoxLimit:
                time.sleep(30 * (attempt + 1))
        raise RuntimeError("Upstox request budget stayed exhausted")

    def _cached(self, name: str, fetch: Any) -> Any:
        p = self.cache / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                pass
        data = fetch()
        p.write_text(json.dumps(data), encoding="utf-8")
        return data

    def contracts(self, underlying_key: str, expiry: str, expired: bool) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            if expired:
                body = self._get("/v2/expired-instruments/option/contract", {"instrument_key": underlying_key, "expiry_date": expiry})
            else:
                body = self._get("/v2/option/contract", {"instrument_key": underlying_key, "expiry_date": expiry})
            return [{"key": x["instrument_key"], "strike": x["strike_price"], "type": x["instrument_type"], "expiry": str(x["expiry"])[:10]} for x in body.get("data") or []]

        return self._cached(f"contracts_{underlying_key.split('|')[-1]}_{expiry}.json", fetch)

    def expiries(self, underlying_key: str) -> list[str]:
        def fetch() -> list[str]:
            live = {str(x["expiry"])[:10] for x in self._get("/v2/option/contract", {"instrument_key": underlying_key}).get("data") or []}
            try:
                dead = set(self._get("/v2/expired-instruments/expiries", {"instrument_key": underlying_key}).get("data") or [])
            except Exception:                              # noqa: BLE001 - expired list is optional
                dead = set()
            return sorted(live | {str(x)[:10] for x in dead})

        return self._cached(f"expiries_{underlying_key.split('|')[-1]}_{date.today().isoformat()}.json", fetch)

    def candles(self, key: str, day: str, expired: bool) -> list[tuple[int, float, float, float, float]]:
        def fetch() -> list[list[Any]]:
            if expired:
                body = self._get(f"/v2/expired-instruments/historical-candle/{up.quote(key, safe='')}/1minute/{day}/{day}", {})
            elif day == datetime.now(IST).date().isoformat():
                body = self._get(f"/v3/historical-candle/intraday/{key}/minutes/1", {})
            else:
                body = self._get(f"/v3/historical-candle/{key}/minutes/1/{day}/{day}", {})
            return (body.get("data") or {}).get("candles") or []

        raw = self._cached(f"c_{key.replace('|', '_')}_{day}.json", fetch)
        out = []
        for c in raw:
            ts = datetime.fromisoformat(str(c[0]))
            out.append((ts.hour * 60 + ts.minute, float(c[1]), float(c[2]), float(c[3]), float(c[4])))
        return sorted(out)


def pick_contract(contracts: list[dict[str, Any]], bull: bool, spot: float) -> dict[str, Any] | None:
    side = "CE" if bull else "PE"
    want = spot * (1 - ITM_PCT / 100.0 if bull else 1 + ITM_PCT / 100.0)
    legs = [c for c in contracts if c["type"] == side]
    return min(legs, key=lambda c: abs(c["strike"] - want)) if legs else None


def signals(day: str, root: Path = ROOT) -> list[dict[str, str]]:
    p = root / "data" / "missed_opportunities" / day / "signals.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def run_day(day: str, src: Source, root: Path = ROOT, underlyings: dict[str, str] | None = None) -> Path | None:
    sigs = signals(day, root)
    if not sigs:
        return None
    underlyings = underlyings or _underlyings(src, root)
    today = datetime.now(IST).date().isoformat()
    rows: list[dict[str, Any]] = []
    for s in sigs:
        sym, minute = s["symbol"], _mins(s.get("first_ready", ""))
        ukey = underlyings.get(sym)
        try:
            spot = float(s.get("entry_price") or 0)
        except ValueError:
            spot = 0.0
        if not ukey or minute is None or spot <= 0:
            continue
        try:
            exps = [e for e in src.expiries(ukey) if e >= day]
            if not exps:
                continue
            expiry = exps[0]
            expired = expiry < today
            ct = pick_contract(src.contracts(ukey, expiry, expired), s["direction"] == "BULLISH", spot)
            if ct is None:
                continue
            bars = src.candles(ct["key"], day, expired)
        except Exception as exc:                           # noqa: BLE001 - one bad contract must not stop the run
            print(day, sym, "skipped:", str(exc)[:100], flush=True)
            continue
        for d in DELAYS:
            lab = label(bars, minute, d)
            if lab:
                rows.append({"day": day, "symbol": sym, "dir": s["direction"], "fate": s.get("fate", ""), "ready": s.get("first_ready", ""), "delay": d, "expiry": expiry,
                             "strike": ct["strike"], "spot": spot, **lab})
    out = root / "data" / "strict_labels"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def _underlyings(src: Source, root: Path) -> dict[str, str]:
    sys.path.insert(0, str(root))
    from order_book_recorder import _universe

    out = {}
    for sym, sid in _universe().items():
        key = src.client.instrument_key("NSE_EQ", sid)
        if key:
            out[sym] = key
    return out


def summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, str]] = []
    for p in sorted(glob.glob(str(root / "data" / "strict_labels" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})

    def table(title: str, keyf: Any, only: Any = None) -> list[str]:
        out = [f"## {title}", "", "| Group | Signals | Hit +10% first | Stop first | Hit +10% within 30 min | Median minutes to +10% |", "|---|---|---|---|---|---|"]
        g: dict[str, list[dict[str, str]]] = defaultdict(list)
        for r in rows:
            if only is None or only(r):
                g[keyf(r)].append(r)
        for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
            t = [float(r["min_to_hit10"]) for r in v if r["min_to_hit10"] != ""]
            out.append(f"| {k} | {len(v)} | {100 * sum(int(r['hit10_first']) for r in v) / len(v):.0f}% | {100 * sum(int(r['stop_first']) for r in v) / len(v):.0f}% | "
                       f"{100 * sum(int(r['hit10_30']) for r in v) / len(v):.0f}% | {(f'{st.median(t):.0f}' if t else '-')} |")
        return out + [""]

    md = ["# Strict label: option reaches +10% before -20% (minute candles, hindsight on which signals; entry = signal time + delay, +1% slippage)", "",
          f"{len(rows)} rows over {len(days)} days ({days[0]} to {days[-1]}). A minute that touches both levels counts as a stop. Research only.", ""]
    md += table("By entry delay", lambda r: f"{r['delay']} min after the signal")
    md += table("By side and delay", lambda r: f"{r['dir']} / {r['delay']} min")
    md += table("By what our system did (10 min delay)", lambda r: r["fate"].split(":")[0], lambda r: r["delay"] == "10")
    md += table("By signal hour (10 min delay)", lambda r: r["ready"][:2], lambda r: r["delay"] == "10")
    path = root / "data" / "strict_labels" / "summary.md"
    path.write_text("\n".join(md), encoding="utf-8")
    return path


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                      # noqa: BLE001
        pass
    days = sys.argv[1:] or sorted(Path(p).parent.name for p in glob.glob(str(ROOT / "data" / "missed_opportunities" / "20*" / "signals.csv")))
    src = Source()
    und = _underlyings(src, ROOT)
    for d in days:
        print(d, run_day(d, src, ROOT, und), "calls so far", src.calls, flush=True)
    print(summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
