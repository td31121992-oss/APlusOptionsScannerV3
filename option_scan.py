"""Full-universe option scan: how did every F&O stock's ATM option move each day, and did we trade it? (research only; hindsight)

For every stock and day, the trade direction is the stock's bigger excursion from its open (up = call, down = put). The nearest-expiry ATM option is priced
from two entry points - 09:20 (anyone just watching the open) and the stock's first 5-minute close at +1% from the open in that direction ("early mover" entry) -
and held to the close, +1% added to the entry price like the other shadow reports. Stocks that never reached +1% get only the 09:20 entry.

    data/shadow_rules/option_scan/<day>.csv     one row per stock-day
    data/shadow_rules/option_scan.md            summary: how many options ran +30% / +50% / +100%, what we traded, what was missed and why

Hindsight: choosing the direction after the day is not a tradable rule. This shows what was on the table, not what a rule could have taken.

    python option_scan.py [YYYY-MM-DD ...]     (candles from data/pattern_log/candles/<day>.json)
"""

from __future__ import annotations

import csv
import glob
import json
import os
import statistics as st
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import big_movers_review as bm
import put_continuation as pc
from sector_groups import fine_map

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
FIELDS = ["day", "symbol", "sector", "dir", "stock_move_pct", "stock_close_pct", "mark1", "outcome", "first_signal",
          "a_entry", "a_best_pct", "a_worst_pct", "a_close_pct", "a_stop_first", "b_entry", "b_best_pct", "b_close_pct", "b_stop_first", "contract"]


_TOKEN: dict[str, Any] = {"value": "", "at": 0.0}


def _legs(master: Any, symbol: str, day: str, side: str) -> Any:
    m = master[(master.UNDERLYING_SYMBOL == symbol) & (master.INSTRUMENT == "OPTSTK") & (master.OPTION_TYPE == side)].copy()
    m["exp"] = m.SM_EXPIRY_DATE.astype(str).str[:10]
    m = m[m.exp >= day]
    if m.empty:
        return None
    return m[m.exp == m.exp.min()].copy()


def fetch_bars(security_id: int, day: str, tries: int = 4) -> list[tuple[int, float, float, float, float]]:
    """5-minute bars of an option for one day, with retries on rate limits."""
    import requests
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    if time.time() - _TOKEN["at"] > 1500 or not _TOKEN["value"]:          # resolve once per 25 minutes: parallel runs must not fight over the token file
        _TOKEN["value"], _TOKEN["at"] = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip()), time.time()
    tok = _TOKEN["value"]
    for attempt in range(tries):
        time.sleep(0.4 * (attempt + 1))
        try:
            r = requests.post("https://api.dhan.co/v2/charts/intraday", timeout=30,
                              headers={"access-token": tok, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"},
                              json={"securityId": str(security_id), "exchangeSegment": "NSE_FNO", "instrument": "OPTSTK", "interval": "5", "oi": False,
                                    "fromDate": f"{day} 09:00:00", "toDate": f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()} 15:30:00"})
        except requests.RequestException:
            continue
        if r.status_code == 200:
            d = r.json()
            out = []
            for t, o, h, l, c in zip(d.get("timestamp") or [], d.get("open") or [], d.get("high") or [], d.get("low") or [], d.get("close") or []):
                x = datetime.fromtimestamp(int(t), IST)
                if x.date().isoformat() == day:
                    out.append((x.hour * 60 + x.minute, float(o), float(h), float(l), float(c)))
            return out
        if r.status_code not in (429, 500, 502, 503, 504, 805):
            break
    return []


def path_stats(bars: list[tuple[int, float, float, float, float]], minute: int) -> dict[str, Any]:
    """Entry = close of the last bar starting at/before `minute` (+1%); best / worst / close afterwards and whether -20% came before +15%."""
    at = [b for b in bars if b[0] <= minute]
    after = [b for b in bars if at and b[0] > at[-1][0]]
    if not at or len(after) < 3:
        return {}
    entry = at[-1][4] * 1.01
    if entry <= 0:
        return {}
    stop_first = False
    for b in after:
        if b[3] <= entry * 0.80:
            stop_first = True
            break
        if b[2] >= entry * 1.15:
            break
    return {"entry": round(entry, 2), "best": round((max(b[2] for b in after) / entry - 1) * 100, 1),
            "worst": round((min(b[3] for b in after) / entry - 1) * 100, 1), "close": round((after[-1][4] / entry - 1) * 100, 1), "stop_first": bool(stop_first)}


def scan_day(day: str, symbols: dict[str, dict[str, Any]], sectors: dict[str, str], signals: list[dict[str, Any]], traded: set[tuple[str, str]],
             master: Any, fetch: Callable[[int, str], list] = fetch_bars) -> list[dict[str, Any]]:
    first_sig: dict[tuple[str, str], dict[str, Any]] = {}
    for r in sorted(signals, key=lambda x: str(x.get("ready"))):
        first_sig.setdefault((r["symbol"], r.get("dir")), r)
    rows = []
    for s, d in sorted(symbols.items()):
        m = d.get("minute") or []
        if len(m) < bm.MIN_BARS or float(d["open"][0]) <= 0:
            continue
        o = float(d["open"][0])
        up, dn = (max(float(x) for x in d["high"]) / o - 1) * 100, (1 - min(float(x) for x in d["low"]) / o) * 100
        sgn = 1 if up >= dn else -1
        side = "CE" if sgn > 0 else "PE"
        direction = "BULLISH" if sgn > 0 else "BEARISH"
        mark1 = next((int(mm) for mm, c in zip(m, d["close"]) if sgn * (float(c) / o - 1) * 100 >= 1.0), None)
        legs = _legs(master, s, day, side)
        row = {"day": day, "symbol": s, "sector": sectors.get(s, "Other"), "dir": direction, "stock_move_pct": round(max(up, dn), 2),
               "stock_close_pct": round(sgn * (float(d["close"][-1]) / o - 1) * 100, 2), "mark1": bm._hm(mark1) if mark1 is not None else ""}
        sig = first_sig.get((s, direction))
        is_traded = (s, direction) in traded or (sig is not None and str(sig.get("fate")) == "TRADED")
        row["outcome"] = "TRADED" if is_traded else (str(sig["fate"]) if sig else "NO_SIGNAL")
        row["first_signal"] = sig["ready"] if sig else ""
        if legs is not None and not legs.empty:
            def price_at(minute: int) -> float:
                idx = [i for i, mm in enumerate(m) if mm <= minute]
                return float(d["close"][idx[-1]]) if idx else o
            for tag, minute in (("a", 9 * 60 + 20), ("b", mark1)):
                if minute is None:
                    continue
                legs = legs.copy()
                legs["d"] = (legs.STRIKE_PRICE.astype(float) - price_at(minute)).abs()
                leg = legs.sort_values("d").iloc[0]
                bars = fetch(int(leg.SECURITY_ID), day)
                ps = path_stats(bars, minute)
                if ps:
                    row[f"{tag}_entry"], row[f"{tag}_best_pct"], row[f"{tag}_worst_pct"], row[f"{tag}_close_pct"], row[f"{tag}_stop_first"] = (
                        ps["entry"], ps["best"], ps["worst"], ps["close"], ps["stop_first"])
                    row["contract"] = f"{s} {int(float(leg.STRIKE_PRICE)) if float(leg.STRIKE_PRICE).is_integer() else leg.STRIKE_PRICE} {side}"
        rows.append(row)
    return rows


def run(day: str, root: Path = ROOT, symbols: dict[str, Any] | None = None, fetch: Callable[[int, str], list] = fetch_bars, master: Any = None) -> Path | None:
    if symbols is None:
        try:
            symbols = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
        except (OSError, ValueError):
            return None
    try:
        sigs = [r for r in json.loads((root / "data" / "missed_opportunities" / day / "option_returns.json").read_text(encoding="utf-8")) if r.get("kind") == "ATM"]
    except (OSError, ValueError):
        sigs = []
    if master is None:
        import pandas as pd

        master = pd.read_csv(root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                             usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"])
    rows = scan_day(day, symbols, fine_map(pc.sector_map(root)), sigs, bm._traded_set(day, root), master, fetch)
    folder = root / "data" / "shadow_rules" / "option_scan"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    write_summary(root)
    return path


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def write_summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "option_scan" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})
    priced = [r for r in rows if _f(r.get("a_best_pct")) is not None]
    out = ["# Full-universe option scan (hindsight, research only)", "",
           f"{len(rows)} stock-days ({len({r['symbol'] for r in rows})} stocks, {len(days)} days, {days[0]} to {days[-1]}); {len(priced)} with an option priced. "
           "Direction = the stock's bigger move from its open; ATM option of the nearest expiry, entry +1%, held to close, before costs.", ""]
    for tag, label in (("a", "Entry 09:20"), ("b", "Entry at the stock's first close +1% from open")):
        g = [r for r in rows if _f(r.get(f"{tag}_best_pct")) is not None]
        if not g:
            continue
        best = [_f(r[f"{tag}_best_pct"]) for r in g]
        close = [_f(r[f"{tag}_close_pct"]) for r in g]
        out += [f"## {label}", "", f"{len(g)} options priced. Best (peak) gain: median {st.median(best):+.0f}%; closed up {100 * sum(x > 0 for x in close) / len(g):.0f}%, "
                f"mean close {st.mean(close):+.1f}%.", "", "| Option peak gain | Options | Share | Traded | Missed |", "|---|---|---|---|---|"]
        for lo in (30, 50, 100):
            h = [r for r in g if _f(r[f"{tag}_best_pct"]) >= lo]
            t = sum(1 for r in h if r["outcome"] == "TRADED")
            out.append(f"| +{lo}% or more | {len(h)} | {100 * len(h) / len(g):.0f}% | {t} | {len(h) - t} |")
        h50 = [r for r in g if _f(r[f"{tag}_best_pct"]) >= 50 and r["outcome"] != "TRADED"]
        reasons = Counter(r["outcome"].split(":")[0] if not r["outcome"].startswith("A_PLUS") else r["outcome"] for r in h50)
        if h50:
            out += ["", f"Why the +50% options were missed: " + ", ".join(f"{k} {v}" for k, v in reasons.most_common(8)) + ".", ""]
        by_sec = defaultdict(list)
        for r in g:
            by_sec[r["sector"]].append(_f(r[f"{tag}_best_pct"]))
        out += ["| Sector | Options | Median peak gain | Share +50% |", "|---|---|---|---|"]
        for k, v in sorted(by_sec.items(), key=lambda kv: -st.median(kv[1]))[:10]:
            out.append(f"| {k} | {len(v)} | {st.median(v):+.0f}% | {100 * sum(x >= 50 for x in v) / len(v):.0f}% |")
        out.append("")
    last = [r for r in priced if r["day"] == days[-1] and r["outcome"] != "TRADED"]
    last.sort(key=lambda r: -(_f(r.get("a_best_pct")) or 0))
    if last:
        out += [f"## Biggest option moves not traded on {days[-1]}", "", "| Stock | Option | Stock move | Peak gain from 09:20 | Close | Outcome |", "|---|---|---|---|---|---|"]
        out += [f"| {r['symbol']} | {r['contract']} | {r['stock_move_pct']}% | {r['a_best_pct']}% | {r['a_close_pct']}% | {r['outcome']} |" for r in last[:12]]
    out += ["", "_Hindsight: the direction is picked after the day, so this is what was on the table, not a rule. Research only._", ""]
    path = root / "data" / "shadow_rules" / "option_scan.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    import sys

    for d in sys.argv[1:] or [date.today().isoformat()]:
        print(d, run(d), flush=True)
    print(write_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
