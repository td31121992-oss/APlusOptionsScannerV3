"""Relative opening volume ("stocks in play") replay (read-only research; no trading effect).

Idea (Zarattini, Barbon, Aziz 2024, "A Profitable Day Trading Strategy For The U.S. Equity Market"): trade only stocks with unusually heavy volume right after the open. Relative opening volume
(RVOL) of a stock on a day = volume of its first 5-minute bar (09:15) divided by the average first-bar volume of the previous 14 sessions (at least 10 needed). It is known from 09:20, so
there is no look-ahead. Variants tested on every closed paper trade since the baseline day:

    RVOL >= 1.5 / 2 / 3                       the stock was in play that morning
    top 20 / top 10 of the day by RVOL        the paper's "top 20 stocks in play", out of our 218 stocks
    in play AND the trade side agrees with the direction of the first 5-minute bar    (call after a green opening bar, put after a red one)

Upstox answers a 5-minute history request only up to about one month, so the history is fetched in 28-day chunks and only the opening bars are cached (data/cache/rvol_first_bars.json).

    python rvol_replay.py
"""

from __future__ import annotations

import json
import random
import statistics as st
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "cache" / "rvol_first_bars.json"
FIRST_DAY = date(2026, 9, 1)                                 # early enough for a 14-session average before the first trade
CHUNK_DAYS = 28
IST = timezone(timedelta(hours=5, minutes=30))


def chunks(first: date, last: date) -> list[tuple[date, date]]:
    out, start = [], first
    while start <= last:
        end = min(start + timedelta(days=CHUNK_DAYS - 1), last)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


def opening_bars(payload: dict[str, list[Any]]) -> dict[str, dict[str, float]]:
    """day -> {v5, o5, c5, v15} from one history answer (lists open / close / volume / timestamp)."""
    out: dict[str, dict[str, float]] = {}
    for i, ts in enumerate(payload.get("timestamp") or []):
        t = datetime.fromtimestamp(int(ts), IST)
        minute = t.hour * 60 + t.minute
        if not 555 <= minute <= 565:                         # 09:15, 09:20, 09:25 bars
            continue
        row = out.setdefault(t.date().isoformat(), {"v5": 0.0, "o5": 0.0, "c5": 0.0, "v15": 0.0})
        vol = float(payload["volume"][i] or 0)
        row["v15"] += vol
        if minute == 555:
            row["v5"], row["o5"], row["c5"] = vol, float(payload["open"][i]), float(payload["close"][i])
    return out


def fetch_all(universe: dict[str, int]) -> dict[str, dict[str, dict[str, float]]]:
    from core import market_data

    cache: dict[str, dict[str, dict[str, float]]] = {}
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    last = date.today() - timedelta(days=1)
    for n, (sym, sid) in enumerate(sorted(universe.items())):
        have = cache.get(sym, {})
        if have and max(have) >= (last - timedelta(days=5)).isoformat():
            continue
        merged = dict(have)
        for a, b in chunks(FIRST_DAY, last):
            d = market_data.chart_call("charts/intraday", {"securityId": str(sid), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "interval": "5",
                                                          "fromDate": f"{a} 09:00:00", "toDate": f"{b} 15:30:00"})
            if d:
                merged.update(opening_bars(d))
            time.sleep(0.15)
        cache[sym] = merged
        if n % 20 == 0:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  fetched {n}/{len(universe)} stocks", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def rvol(history: dict[str, dict[str, float]], day: str, lookback: int = 14, need: int = 10) -> float | None:
    prior = sorted(d for d in history if d < day)[-lookback:]
    vols = [history[d]["v5"] for d in prior if history[d]["v5"] > 0]
    today = history.get(day, {}).get("v5", 0.0)
    return today / st.mean(vols) if len(vols) >= need and today > 0 else None


def summary(pnls: list[float]) -> str:
    if not pnls:
        return "n=  0"
    random.seed(13)
    lo = hi = float("nan")
    if len(pnls) >= 8:
        m = sorted(sum(random.choices(pnls, k=len(pnls))) / len(pnls) for _ in range(2000))
        lo, hi = m[50], m[1950]
    return f"n={len(pnls):3d} win={100 * sum(1 for x in pnls if x > 0) / len(pnls):3.0f}% net={sum(pnls):9,.0f} avg={st.mean(pnls):6.0f} (95% {lo:6.0f}..{hi:6.0f})"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import shadow_scoreboard as sb
    from dotenv import load_dotenv
    from order_book_recorder import _universe

    load_dotenv(ROOT / ".env")
    trades = sb.load_trades(upto=date.today().isoformat())
    cache = fetch_all(_universe())
    days = sorted({t["_day"] for t in trades})
    rv: dict[tuple[str, str], float] = {}
    for day in sorted({d for h in cache.values() for d in h}):
        for sym, hist in cache.items():
            r = rvol(hist, day)
            if r is not None:
                rv[(sym.upper(), day)] = r
    rank: dict[tuple[str, str], int] = {}
    for day in days:
        today = sorted(((r, s) for (s, d), r in rv.items() if d == day), reverse=True)
        for i, (_, s) in enumerate(today):
            rank[(s, day)] = i + 1

    def key(t: dict[str, Any]) -> tuple[str, str]:
        return str(t["symbol"]).upper(), t["_day"]

    usable = [t for t in trades if key(t) in rv]
    pnl = lambda t: float(t["net_pnl"])                                           # noqa: E731
    good = lambda t: (sb._f(t.get("mfe_amount")) or 0) >= 3000                    # noqa: E731
    print(f"{len(trades)} closed trades; opening-volume data for {len(usable)} of them ({len({t['_day'] for t in usable})} days)\n")
    print("RVOL of the traded stock (first 5-minute bar vs its 14-session average):")
    vals = sorted(rv[key(t)] for t in usable)
    print(f"  median {st.median(vals):.2f}  p75 {vals[3 * len(vals) // 4]:.2f}  p90 {vals[int(.9 * len(vals))]:.2f}   (1.0 = a normal opening)\n")

    def direction_ok(t: dict[str, Any]) -> bool | None:
        h = cache.get(str(t["symbol"]).upper(), {}).get(t["_day"])
        if not h or not h["o5"]:
            return None
        up = h["c5"] > h["o5"]
        return (str(t.get("option_type")).upper() == "CE") == up

    first_half = set(days[: len(days) // 2])

    def report(label: str, rule: Callable[[dict[str, Any]], bool]) -> None:
        kept = [t for t in usable if rule(t)]
        gone = [t for t in usable if not rule(t)]
        a, b = sum(pnl(t) for t in kept if t["_day"] in first_half), sum(pnl(t) for t in kept if t["_day"] not in first_half)
        share = 100 * sum(1 for t in kept if good(t)) / max(1, len(kept))
        print(f"{label:46s} {summary([pnl(t) for t in kept])} | touched 3k: {share:3.0f}% | removed n={len(gone):3d} net={sum(pnl(t) for t in gone):9,.0f} | halves {a:8,.0f} / {b:8,.0f}")

    report("all trades (no rule)", lambda t: True)
    for th in (1.5, 2.0, 3.0):
        report(f"RVOL >= {th}", lambda t, th=th: rv[key(t)] >= th)
    report("below 1.0 (quiet opening)", lambda t: rv[key(t)] < 1.0)
    for n in (20, 10):
        report(f"top {n} of the day by RVOL", lambda t, n=n: rank.get(key(t), 999) <= n)
    for th in (1.5, 2.0):
        report(f"RVOL >= {th} and side agrees with 1st bar", lambda t, th=th: rv[key(t)] >= th and direction_ok(t) is True)
    report("side agrees with the first 5-minute bar", lambda t: direction_ok(t) is True)
    report("side against the first 5-minute bar", lambda t: direction_ok(t) is False)
    print("\nRVOL buckets:")
    for lo_, hi_ in ((0, 0.7), (0.7, 1.0), (1.0, 1.5), (1.5, 2.5), (2.5, 99)):
        report(f"  {lo_:3.1f} <= RVOL < {hi_:4.1f}", lambda t, lo_=lo_, hi_=hi_: lo_ <= rv[key(t)] < hi_)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
