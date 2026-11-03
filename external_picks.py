"""Log of picks from OTHER tools (Quant Elite Pro, Trade Lab, ...) and how they did - so we can compare their selection with ours (research only; no trading effect).

    python external_picks.py add --source QuantElite --symbol TECHM --dir BULLISH --time 09:39 --price 1738 [--note "..."] [--day YYYY-MM-DD]
    python external_picks.py review [YYYY-MM-DD ...]        (also run every night by missed_option_returns)
    python external_picks.py list [YYYY-MM-DD]

    data/external_picks/<day>.csv            one row per pick: day, source, symbol, dir, time, price, note
    data/external_picks/review/<day>.csv     for each pick: stock move from the listing time to the close, ATM option from that moment (peak / close / stop first),
                                             and what OUR system did with the same stock that day (TRADED, the A+ rule that held it, V2_BLOCKED, NO_SIGNAL)
    data/external_picks/review.md            per source: picks, stock hit rate, mean stock move, mean option close, and how many we had traded / missed

A pick with no listing time is measured from 09:25 (after the opening noise). Direction is the side the tool suggested (BULLISH = buy / calls, BEARISH = sell / puts).
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
FIELDS = ["day", "source", "symbol", "dir", "time", "price", "note"]
REVIEW_FIELDS = ["day", "source", "symbol", "dir", "time", "stock_to_close_pct", "stock_best_pct", "stock_worst_pct", "opt_best_pct", "opt_close_pct", "opt_stop_first",
                 "our_fate", "first_signal"]
DEFAULT_MINUTE = 9 * 60 + 25


def _mins(h: str) -> int | None:
    try:
        a, b = str(h).split(":")[:2]
        return int(a) * 60 + int(b)
    except (ValueError, AttributeError):
        return None


def add(day: str, source: str, symbol: str, direction: str, time: str = "", price: str | float = "", note: str = "", root: Path = ROOT) -> Path:
    direction = str(direction).upper()
    direction = "BULLISH" if direction in ("BULLISH", "BUY", "B", "CE", "LONG") else "BEARISH"
    folder = root / "data" / "external_picks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as h:
            rows = list(csv.DictReader(h))
    key = (source, symbol.upper(), direction)
    rows = [r for r in rows if (r["source"], r["symbol"], r["dir"]) != key]            # adding the same pick again replaces it
    rows.append({"day": day, "source": source, "symbol": symbol.upper(), "dir": direction, "time": time, "price": price, "note": note})
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def load(day: str, root: Path = ROOT) -> list[dict[str, str]]:
    path = root / "data" / "external_picks" / f"{day}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def _our_fate(day: str, symbol: str, direction: str, root: Path) -> tuple[str, str]:
    try:
        data = json.loads((root / "data" / "missed_opportunities" / day / "option_returns.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    first = None
    for r in sorted((x for x in data if x.get("kind") == "ATM" and x.get("symbol") == symbol and x.get("dir") == direction), key=lambda x: str(x.get("ready"))):
        first = r
        break
    if first is None:
        return "NO_SIGNAL", ""
    return str(first.get("fate") or ""), str(first.get("ready") or "")


def run(day: str, root: Path = ROOT, fetch: Callable[[int, str], list] | None = None, master: Any = None) -> Path | None:
    picks = load(day, root)
    if not picks:
        return None
    try:
        symbols = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        return None
    import option_scan as osn
    import put_continuation as pc

    fetch = fetch or osn.fetch_bars
    if master is None:
        try:
            import pandas as pd

            master = pd.read_csv(root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                                 usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"])
        except Exception:                                  # noqa: BLE001 - the option half is an extra
            master = None
    out = []
    for p in picks:
        d = symbols.get(p["symbol"])
        if not d or not d.get("minute"):
            continue
        sg = 1 if p["dir"] == "BULLISH" else -1
        minute = _mins(p.get("time", "")) or DEFAULT_MINUTE
        idx = [i for i, m in enumerate(d["minute"]) if m <= minute]
        if not idx:
            continue
        i0 = idx[-1]
        px = float(d["close"][i0])
        rest_hi = max(float(x) for x in d["high"][i0:])
        rest_lo = min(float(x) for x in d["low"][i0:])
        row = {"day": day, "source": p["source"], "symbol": p["symbol"], "dir": p["dir"], "time": p.get("time", "") or f"{minute // 60:02d}:{minute % 60:02d} (default)",
               "stock_to_close_pct": round(sg * (float(d["close"][-1]) / px - 1) * 100, 2),
               "stock_best_pct": round(sg * ((rest_hi if sg > 0 else rest_lo) / px - 1) * 100, 2),
               "stock_worst_pct": round(sg * ((rest_lo if sg > 0 else rest_hi) / px - 1) * 100, 2)}
        row["our_fate"], row["first_signal"] = _our_fate(day, p["symbol"], p["dir"], root)
        if master is not None:
            try:
                m = master[(master.UNDERLYING_SYMBOL == p["symbol"]) & (master.INSTRUMENT == "OPTSTK") & (master.OPTION_TYPE == ("CE" if sg > 0 else "PE"))].copy()
                m["exp"] = m.SM_EXPIRY_DATE.astype(str).str[:10]
                m = m[m.exp >= day]
                if not m.empty:
                    m = m[m.exp == m.exp.min()].copy()
                    m["dist"] = (m.STRIKE_PRICE.astype(float) - px).abs()
                    ps = osn.path_stats(fetch(int(m.sort_values("dist").iloc[0].SECURITY_ID), day), minute)
                    if ps:
                        row.update({"opt_best_pct": ps["best"], "opt_close_pct": ps["close"], "opt_stop_first": int(ps["stop_first"])})
            except Exception:                              # noqa: BLE001
                pass
        out.append(row)
    folder = root / "data" / "external_picks" / "review"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    write_summary(root)
    return path


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def write_summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "external_picks" / "review" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})
    out = ["# External picks: how other tools' selections did (research only)", "",
           f"{len(rows)} picks on {len(days)} day(s) ({days[0]} to {days[-1]}). Stock move = from the listing time (or 09:25 if none) to the close, in the pick's direction; "
           "the option is the ATM option of the nearest expiry bought at that moment (hindsight, before costs).", "",
           "| Source | Picks | Stock up at close | Mean stock move | Mean best excursion | Mean option close | Option up | We traded | We held back | We had no signal |", "|---|---|---|---|---|---|---|---|---|---|"]
    by = defaultdict(list)
    for r in rows:
        by[r["source"]].append(r)
    for src, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
        mv = [_f(r["stock_to_close_pct"]) for r in g if _f(r["stock_to_close_pct"]) is not None]
        bx = [_f(r["stock_best_pct"]) for r in g if _f(r["stock_best_pct"]) is not None]
        oc = [_f(r["opt_close_pct"]) for r in g if _f(r.get("opt_close_pct")) is not None]
        traded = sum(1 for r in g if r["our_fate"] == "TRADED")
        nosig = sum(1 for r in g if r["our_fate"] == "NO_SIGNAL")
        held = sum(1 for r in g if r["our_fate"] and r["our_fate"] not in ("TRADED", "NO_SIGNAL"))
        out.append(f"| {src} | {len(g)} | {(f'{100 * sum(x > 0 for x in mv) / len(mv):.0f}%' if mv else '-')} | {(f'{st.mean(mv):+.2f}%' if mv else '-')} | "
                   f"{(f'{st.mean(bx):+.2f}%' if bx else '-')} | {(f'{st.mean(oc):+.1f}%' if oc else '-')} | {(f'{100 * sum(x > 0 for x in oc) / len(oc):.0f}%' if oc else '-')} | "
                   f"{traded} | {held} | {nosig} |")
    out += ["", "## By day", "", "| Day | Source | Symbol | Way | From | Stock to close | Best | Option close | Our system |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["day"], x["source"], x["symbol"])):
        out.append(f"| {r['day']} | {r['source']} | {r['symbol']} | {r['dir'].title()} | {r['time']} | {r['stock_to_close_pct']}% | {r['stock_best_pct']}% | "
                   f"{(r.get('opt_close_pct') or '-')}{'%' if r.get('opt_close_pct') else ''} | {r['our_fate'] or '-'}{(' @' + r['first_signal']) if r['first_signal'] else ''} |")
    out += ["", "_Research only. A few days of picks cannot show an edge; look at the hit rate again after 10+ days._", ""]
    path = root / "data" / "external_picks" / "review.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--source", required=True)
    a.add_argument("--symbol", required=True)
    a.add_argument("--dir", required=True)
    a.add_argument("--time", default="")
    a.add_argument("--price", default="")
    a.add_argument("--note", default="")
    a.add_argument("--day", default=date.today().isoformat())
    r = sub.add_parser("review")
    r.add_argument("days", nargs="*")
    ls = sub.add_parser("list")
    ls.add_argument("day", nargs="?", default=date.today().isoformat())
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                      # noqa: BLE001
        pass
    if args.cmd == "add":
        print(add(args.day, args.source, args.symbol, args.dir, args.time, args.price, args.note))
    elif args.cmd == "review":
        for d in args.days or [date.today().isoformat()]:
            print(d, run(d), flush=True)
        print(write_summary())
    else:
        for p in load(args.day):
            print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
